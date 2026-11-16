#!/usr/bin/env python3
"""
Açılış Botu — price action taramasını açılıştan hemen önce yapar, listeyi Telegram'a
gönderir, açılıştan sonra ilk dakikalarda giriş tetiklerini izleyip bildirir.
İŞLEM AÇMAZ. Sadece bildirim gönderir; kararı ve emri siz verirsiniz.

Gerekenler:
    pip install -r requirements.txt
    Ortam değişkenleri: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

Kullanım:
    python acilis_botu.py --telegram-test              (bağlantıyı dener, tek mesaj atar)
    python acilis_botu.py --piyasa sp500 --saf         (normal çalışma: açılışı bekler)
    python acilis_botu.py --piyasa sp500 --saf --test  (beklemeden hemen tarar + bir kez kontrol eder)

Zamanlama: Betik açılışa en fazla --max-bekleme dakika kala başlatılmalı. Daha erken
çalıştırılırsa hiçbir şey yapmadan çıkar. Bu sayede GitHub Actions'ta yaz ve kış saati
için iki ayrı zamanlama tanımlanabilir: hangisi doğru saatteyse o çalışır.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import price_action_tarayici as pat

# Piyasa -> (saat dilimi, açılış saati)
SEANS = {
    "sp500": ("America/New_York", (9, 30)),
    "bist": ("Europe/Istanbul", (10, 0)),
    "bist_likit": ("Europe/Istanbul", (10, 0)),
}
KONTROL_ARALIGI_DK = 5
ACILIS_ARALIGI_DK = 15   # kırılımlarda açılış aralığı (ilk 15 dakika)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def telegram(metin: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[TELEGRAM AYARLI DEĞİL — mesaj sadece ekrana yazıldı]\n" + metin + "\n")
        return
    # Telegram mesaj sınırı 4096 karakter; satır bazında böl
    parcalar, simdiki = [], ""
    for satir in metin.split("\n"):
        if len(simdiki) + len(satir) + 1 > 3900:
            parcalar.append(simdiki)
            simdiki = ""
        simdiki += satir + "\n"
    parcalar.append(simdiki)
    for p in parcalar:
        veri = urllib.parse.urlencode({
            "chat_id": chat, "text": p, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}).encode()
        for deneme in range(3):
            try:
                urllib.request.urlopen(
                    f"https://api.telegram.org/bot{token}/sendMessage", veri, timeout=30)
                break
            except Exception as e:
                print(f"Telegram hatası ({deneme + 1}/3): {e}", file=sys.stderr)
                time.sleep(5)


def e(x) -> str:
    return html.escape(str(x))


def sembol_adi(s: str) -> str:
    return s.removesuffix(".IS").removesuffix("-USD")


# ---------------------------------------------------------------------------
# Mesaj biçimleri
# ---------------------------------------------------------------------------
def liste_mesaji(sinyal, izle, piyasa: str, taranan: int, izleme_dk: int) -> str:
    mod = "SAF" if pat.AYAR["saf"] else "standart"
    m = [f"📊 <b>{e(piyasa.upper())} açılış öncesi tarama</b> ({mod})",
         f"{datetime.now():%d.%m.%Y} · {taranan} hisse tarandı", ""]
    if sinyal:
        m.append("✅ <b>SİNYAL VAR</b>")
        for i, a in enumerate(sinyal, 1):
            m.append(f"{i}. <a href=\"{pat.tradingview_linki(a.sembol)}\"><b>"
                     f"{e(sembol_adi(a.sembol))}</b></a> — {e(a.kurgu)}, puan {a.puan}")
            m.append(f"   Giriş {a.giris:.2f} · Stop {a.stop:.2f} (-%{a.stop_yuzde:.1f})"
                     f" · Hedef {a.hedef:.2f} · R/Ö {a.rr:.1f}")
            for u in a.uyarilar:
                m.append(f"   ⚠ {e(u)}")
    else:
        m.append("✅ Sinyalli aday yok.")
    if izle:
        m += ["", "👀 <b>İZLE</b> (dönüş mumu bekleniyor, tetik bildirimi yok)"]
        for a in izle:
            m.append(f"• <b>{e(sembol_adi(a.sembol))}</b> — giriş ~{a.giris:.2f}, "
                     f"stop {a.stop:.2f}, R/Ö {a.rr:.1f}")
    if sinyal:
        m += ["", f"⏱ Açılıştan sonra ilk {izleme_dk} dk giriş tetiklerini bildireceğim."]
    m += ["", "<i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>"]
    return "\n".join(m)


def rr_simdi(a, fiyat: float) -> float:
    risk = fiyat - a.stop
    return (a.hedef - fiyat) / risk if risk > 0 else 0.0


# ---------------------------------------------------------------------------
# Gün içi takip
# ---------------------------------------------------------------------------
def gun_ici_veri(semboller: list[str], tz: str, bugun) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    df = yf.download(semboller, period="1d", interval="5m", group_by="ticker",
                     auto_adjust=False, prepost=False, threads=True, progress=False)
    sonuc = {}
    for s in semboller:
        try:
            d = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            d = d[["Open", "High", "Low", "Close"]].dropna()
        except KeyError:
            continue
        if d.empty:
            continue
        idx = d.index
        idx = idx.tz_localize("UTC") if idx.tz is None else idx
        d.index = idx.tz_convert(tz)
        d = d[d.index.date == bugun]
        if len(d):
            sonuc[s] = d
    return sonuc


class Takip:
    """Her aday için durum: bekliyor -> tetiklendi / iptal / kaçtı. Her olay bir kez bildirilir."""

    def __init__(self, adaylar):
        self.adaylar = {a.sembol: a for a in adaylar}
        self.durum = {a.sembol: "bekliyor" for a in adaylar}

    def kontrol(self, veri: dict[str, pd.DataFrame], acilis: datetime) -> list[str]:
        mesajlar = []
        for s, a in self.adaylar.items():
            if self.durum[s] != "bekliyor" or s not in veri:
                continue
            d = veri[s]
            ad = f"<b>{e(sembol_adi(s))}</b>"
            son = float(d["Close"].iloc[-1])
            acilis_fiyati = float(d["Open"].iloc[0])
            risk = a.giris - a.stop

            # 1) Açılış boşluğu kontrolü (yalnızca ilk kontrolde anlamlı)
            if acilis_fiyati < a.stop:
                self.durum[s] = "iptal"
                mesajlar.append(f"❌ {ad} stopun altında açıldı ({acilis_fiyati:.2f} < "
                                f"{a.stop:.2f}). Kurgu bozuldu, takip bırakıldı.")
                continue
            if acilis_fiyati > a.giris + 0.5 * risk:
                self.durum[s] = "kaçtı"
                durum = ("hedefin de üstünde" if acilis_fiyati >= a.hedef else
                         f"bu fiyattan R/Ö {rr_simdi(a, acilis_fiyati):.1f}")
                mesajlar.append(f"🚀 {ad} boşlukla yukarı açıldı ({acilis_fiyati:.2f}, giriş "
                                f"{a.giris:.2f}; {durum}) — kovalamayın, geri çekilme bekleyin.")
                continue

            # 2) Stop, girişten önce geldiyse iptal
            if float(d["Low"].min()) <= a.stop and float(d["High"].max()) < a.giris:
                self.durum[s] = "iptal"
                mesajlar.append(f"❌ {ad} giriş tetiklenmeden stop seviyesine indi "
                                f"({a.stop:.2f}). Kurgu iptal.")
                continue

            # 3) Tetik
            if a.kurgu == "Kırılım":
                aralik = d[d.index < acilis + timedelta(minutes=ACILIS_ARALIGI_DK)]
                if len(d) <= len(aralik):          # açılış aralığı henüz tamamlanmadı
                    continue
                ust = float(aralik["High"].max())
                if son > ust and son >= a.giris:
                    self.durum[s] = "tetiklendi"
                    r = rr_simdi(a, son)
                    not_ = "" if r >= 1.5 else " ⚠ R/Ö zayıf; stopu açılış aralığının dibine çekmeyi düşünün."
                    mesajlar.append(
                        f"🟢 {ad} TETİKLENDİ — açılış aralığının tepesini ({ust:.2f}) kırdı. "
                        f"Fiyat {son:.2f} · Stop {a.stop:.2f} · Hedef {a.hedef:.2f} · "
                        f"Güncel R/Ö {r:.1f}{not_}")
            else:
                if float(d["High"].max()) >= a.giris:
                    self.durum[s] = "tetiklendi"
                    r = rr_simdi(a, max(son, a.giris))
                    not_ = "" if r >= 1.5 else " ⚠ Fiyat girişten uzaklaştı, R/Ö zayıfladı."
                    mesajlar.append(
                        f"🟢 {ad} TETİKLENDİ — giriş {a.giris:.2f} geçildi. Fiyat {son:.2f} · "
                        f"Stop {a.stop:.2f} · Hedef {a.hedef:.2f} · Güncel R/Ö {r:.1f}{not_}")
        return mesajlar

    def ozet(self) -> str:
        sembol = {"tetiklendi": "🟢", "iptal": "❌", "kaçtı": "🚀", "bekliyor": "⏳"}
        satir = [f"{sembol[d]} {e(sembol_adi(s))}: {d}" for s, d in self.durum.items()]
        return "📋 <b>İzleme süresi bitti — özet</b>\n" + "\n".join(satir)


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Açılış botu (tarama + Telegram + tetik takibi)")
    ap.add_argument("--piyasa", choices=list(SEANS), default="sp500")
    ap.add_argument("--saf", action="store_true", help="Saf price action modu")
    ap.add_argument("--adet", type=int, default=8, help="Her bölümde en fazla aday")
    ap.add_argument("--izleme", type=int, default=45, help="Açılıştan sonra izleme süresi (dk)")
    ap.add_argument("--max-bekleme", type=int, default=40,
                    help="Açılışa bundan fazla dakika varsa hiçbir şey yapmadan çık")
    ap.add_argument("--gec-tolerans", type=int, default=20,
                    help="Açılıştan bu kadar dakika sonra başlarsa çık (diğer zamanlama çalışmasın)")
    ap.add_argument("--test", action="store_true",
                    help="Saat kontrolü yapma: hemen tara, bir kez kontrol et, çık")
    ap.add_argument("--telegram-test", action="store_true", help="Sadece test mesajı gönder")
    args = ap.parse_args()

    if args.telegram_test:
        telegram("✅ Price action botu bağlantı testi başarılı.")
        print("Test mesajı gönderildi.")
        return
    if args.saf:
        pat.AYAR["saf"] = True

    tz, (sa, dk) = SEANS[args.piyasa]
    simdi = datetime.now(ZoneInfo(tz))
    acilis = simdi.replace(hour=sa, minute=dk, second=0, microsecond=0)
    kalan = (acilis - simdi).total_seconds() / 60

    if not args.test:
        if simdi.weekday() >= 5:
            print("Hafta sonu, çıkılıyor.")
            return
        if kalan > args.max_bekleme:
            print(f"Açılışa {kalan:.0f} dk var (> {args.max_bekleme}). Bu zamanlama bugünün "
                  f"saat dilimine uymuyor (yaz/kış saati); çıkılıyor.")
            return
        if kalan < -min(args.gec_tolerans, args.izleme - 10):
            print(f"Açılış {-kalan:.0f} dk önce oldu; izleme penceresi kaçtı, çıkılıyor.")
            return

    # --- 1) Tarama ve liste mesajı ---
    t = pat.tara(args.piyasa, None, args.adet)
    sinyal, izle = t["sinyal"], t["izle"]
    if kalan < 0 and not args.test:
        print("UYARI: Açılıştan sonra başladı; son günlük mum yarım olabilir.")
    telegram(liste_mesaji(sinyal, izle, args.piyasa, len(t["veri"]), args.izleme))
    if not sinyal:
        return

    # --- 2) Açılış sonrası tetik takibi ---
    takip = Takip(sinyal)
    semboller = [a.sembol for a in sinyal]
    if args.test:
        veri = gun_ici_veri(semboller, tz, datetime.now(ZoneInfo(tz)).date())
        mesajlar = takip.kontrol(veri, acilis)
        telegram("\n\n".join(mesajlar) if mesajlar else
                 f"🧪 Test kontrolü: {len(veri)}/{len(semboller)} hissede gün içi veri var, "
                 f"henüz tetik yok.")
        return

    bitis = acilis + timedelta(minutes=args.izleme)
    ilk_kontrol = acilis + timedelta(minutes=KONTROL_ARALIGI_DK + 1)
    bekle = (ilk_kontrol - datetime.now(ZoneInfo(tz))).total_seconds()
    if bekle > 0:
        print(f"Açılış bekleniyor ({bekle / 60:.0f} dk)...")
        time.sleep(bekle)

    veri_geldi = False
    while datetime.now(ZoneInfo(tz)) <= bitis:
        try:
            veri = gun_ici_veri(semboller, tz, acilis.date())
        except Exception as ex:
            print(f"Gün içi veri hatası: {ex}", file=sys.stderr)
            veri = {}
        if veri:
            veri_geldi = True
            for m in takip.kontrol(veri, acilis):
                telegram(m)
        elif not veri_geldi and datetime.now(ZoneInfo(tz)) > acilis + timedelta(minutes=20):
            telegram("ℹ️ Açılıştan 20 dk sonra hâlâ gün içi veri yok. Bugün piyasa tatil "
                     "olabilir; takip durduruldu.")
            return
        if all(d != "bekliyor" for d in takip.durum.values()):
            break
        time.sleep(KONTROL_ARALIGI_DK * 60)

    telegram(takip.ozet())


if __name__ == "__main__":
    main()
