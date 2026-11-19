#!/usr/bin/env python3
"""
Emtia & Döviz Botu — 20 ürünü (emtia, döviz, endeks) günlük grafikte price action
kurallarıyla tarar ve gün boyunca takip eder. İŞLEM AÇMAZ, sadece bildirim gönderir.

Her 30 dakikada bir çalıştırılır (cron-job.org -> GitHub Actions). Her çalıştırmada:
  - Hafta içi saat 08:00'den sonra o günün listesi henüz yapılmadıysa: tarar, listeyi gönderir.
  - Ardından listedeki ve açık durumdaki ürünleri 15 dakikalık mumlarla kontrol eder;
    yeni bir olay (tetik, iptal, hedef, stop) varsa bildirir.

Durum durum/emtia.json dosyasında, kapanan kurgular durum/emtia_sonuclar.csv dosyasında
tutulur (iş akışı bu klasörü depoya geri kaydeder).

Kullanım:
    python emtia_botu.py            (normal: saat kontrolüyle)
    python emtia_botu.py --test     (hemen tarar + kontrol eder, durum dosyasına yazmaz)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import acilis_botu as ab
import price_action_tarayici as pat

TR = ZoneInfo("Europe/Istanbul")
LISTE_SAATI = 8                     # TR saatiyle sabah listesi
MAX_ACIK_GUN = 10                   # tetiklenen kurgu en fazla bu kadar gün izlenir
DURUM_DOSYASI = os.path.join("durum", "emtia.json")
SONUC_DOSYASI = os.path.join("durum", "emtia_sonuclar.csv")
BEKLEYEN = {"bekliyor"}
ACIK = {"tetiklendi"}

f, e = pat.fmt, ab.e


def ad(s: str) -> str:
    return f"<a href=\"{pat.tradingview_linki(s)}\"><b>{e(pat.gorunen_ad(s))}</b></a>"


# ---------------------------------------------------------------------------
# Durum dosyası
# ---------------------------------------------------------------------------
def durum_oku() -> dict:
    try:
        with open(DURUM_DOSYASI, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"liste_tarihi": None, "adaylar": {}}


def durum_yaz(durum: dict) -> None:
    os.makedirs(os.path.dirname(DURUM_DOSYASI), exist_ok=True)
    with open(DURUM_DOSYASI, "w", encoding="utf-8") as fh:
        json.dump(durum, fh, ensure_ascii=False, indent=1)


def sonuc_kaydet(kayitlar: list[dict]) -> None:
    if not kayitlar:
        return
    os.makedirs(os.path.dirname(SONUC_DOSYASI), exist_ok=True)
    yeni = not os.path.exists(SONUC_DOSYASI)
    alanlar = ["liste_tarihi", "sembol", "ad", "kurgu", "puan", "tetik", "giris", "stop",
               "hedef", "rr_plan", "durum", "tetik_zamani", "kapanis_zamani",
               "kapanis_fiyati", "sonuc_R"]
    with open(SONUC_DOSYASI, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=alanlar, extrasaction="ignore")
        if yeni:
            w.writeheader()
        w.writerows(kayitlar)


# ---------------------------------------------------------------------------
# Sabah listesi
# ---------------------------------------------------------------------------
def liste_yap(durum: dict, simdi: datetime) -> list[dict]:
    """Taramayı yapar, durum dosyasını günceller, kapananları döndürür. Mesajı gönderir."""
    t = pat.tara("emtia", None, adet=10)
    kapananlar = []

    # Dünden kalan, tetiklenmemiş kurguların süresi doldu
    for s, k in list(durum["adaylar"].items()):
        if k["durum"] in BEKLEYEN:
            k.update(durum="süresi doldu", kapanis_zamani=simdi.isoformat(), sonuc_R=0)
            kapananlar.append(k)
            del durum["adaylar"][s]

    yeni = []
    for a in t["sinyal"]:
        if a.sembol in durum["adaylar"]:          # zaten açık bir kurgusu var
            continue
        d = t["veri"][a.sembol]
        # Kırılımda tetik: kırılım mumunun tepesi aşılınca (24 saat işlem gören üründe
        # "açılış aralığı" yok). Geri çekilmede: önerilen giriş seviyesi.
        if a.kurgu == "Kırılım":
            tetik = float(d["High"].iloc[-1])
            hedef = tetik + pat.AYAR["min_rr"] * (tetik - a.stop)   # ölçülü hedef tetikten
        else:
            tetik, hedef = a.giris, a.hedef
        k = {"sembol": a.sembol, "ad": pat.gorunen_ad(a.sembol), "kurgu": a.kurgu,
             "puan": a.puan, "tetik": tetik, "stop": a.stop, "hedef": hedef,
             "rr_plan": round((hedef - tetik) / (tetik - a.stop), 2) if tetik > a.stop else 0,
             "uyarilar": a.uyarilar, "liste_tarihi": simdi.date().isoformat(),
             "liste_zamani": simdi.astimezone(timezone.utc).isoformat(), "durum": "bekliyor"}
        durum["adaylar"][a.sembol] = k
        yeni.append(k)
    durum["liste_tarihi"] = simdi.date().isoformat()

    m = [f"🌍 <b>Emtia &amp; Döviz — günlük tarama</b>",
         f"{simdi:%d.%m.%Y %H:%M} · {len(t['veri'])} ürün · dünkü kapanışlara göre", ""]
    if yeni:
        m.append("✅ <b>SİNYAL VAR</b> (gün boyu 30 dk'da bir izlenecek)")
        for i, k in enumerate(yeni, 1):
            m.append(f"{i}. {ad(k['sembol'])} — {e(k['kurgu'])}, puan {k['puan']}")
            m.append(f"   Tetik {f(k['tetik'])} · Stop {f(k['stop'])} · Hedef {f(k['hedef'])}"
                     f" · R/Ö {k['rr_plan']:.1f}")
            for u in k["uyarilar"]:
                m.append(f"   ⚠ {e(u)}")
    else:
        m.append("Bugün kurallara uyan yeni ürün yok.")
    if t["izle"]:
        m += ["", "👀 <b>İZLE</b> (dönüş mumu bekleniyor, bildirim yok)"]
        for a in t["izle"]:
            m.append(f"• {ad(a.sembol)} — giriş ~{f(a.giris)}, stop {f(a.stop)}, R/Ö {a.rr:.1f}")
    acik = [k for k in durum["adaylar"].values() if k["durum"] in ACIK]
    if acik:
        m += ["", "📂 <b>Açık kurgular</b> (önceki günlerden)"]
        for k in acik:
            m.append(f"• {ad(k['sembol'])} — giriş {f(k['giris'])}, stop {f(k['stop'])}, "
                     f"hedef {f(k['hedef'])}")
    if kapananlar:
        m += ["", f"⌛ Dünden tetiklenmeyen {len(kapananlar)} kurgu listeden çıkarıldı."]
    m += ["", "<i>Bilgi amaçlıdır, yatırım tavsiyesi değildir.</i>"]
    ab.telegram("\n".join(m))
    return kapananlar


# ---------------------------------------------------------------------------
# Gün içi takip
# ---------------------------------------------------------------------------
def gun_ici(semboller: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    df = yf.download(semboller, period="1mo", interval="15m", group_by="ticker",
                     auto_adjust=False, prepost=False, threads=True, progress=False)
    out = {}
    for s in semboller:
        try:
            d = df[s] if isinstance(df.columns, pd.MultiIndex) else df
            d = d[["Open", "High", "Low", "Close"]].dropna()
        except KeyError:
            continue
        if len(d):
            idx = d.index
            d.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
            out[s] = d
    return out


def simule_et(k: dict, d: pd.DataFrame) -> dict:
    """Listeye girdiği andan bu yana mumları sırayla oynatır; kurgunun şu anki durumunu döndürür.
    Aynı mumda hem stop hem hedef/tetik görüldüyse ihtiyatlı davranılır (kötü olan sayılır)."""
    bas = pd.Timestamp(k["liste_zamani"])
    bars = d[d.index >= bas]          # sadece liste yayınlandıktan sonra başlayan mumlar
    tetik, stop, hedef = k["tetik"], k["stop"], k["hedef"]
    risk = tetik - stop
    r = {"durum": "bekliyor"}
    for t, b in bars.iterrows():
        if r["durum"] == "bekliyor":
            if b["Open"] > tetik + 0.5 * risk:
                return {"durum": "kaçtı", "kapanis_zamani": t.isoformat(),
                        "kapanis_fiyati": float(b["Open"]), "sonuc_R": 0}
            if b["Low"] <= stop:
                return {"durum": "iptal", "kapanis_zamani": t.isoformat(),
                        "kapanis_fiyati": float(stop), "sonuc_R": 0}
            if b["High"] >= tetik:
                giris = max(tetik, float(b["Open"]))
                r = {"durum": "tetiklendi", "giris": giris, "tetik_zamani": t.isoformat()}
                if b["Close"] <= stop:          # aynı mumda stopa da indiyse
                    return {**r, "durum": "stop", "kapanis_zamani": t.isoformat(),
                            "kapanis_fiyati": float(stop), "sonuc_R": -1.0}
                continue
        elif r["durum"] == "tetiklendi":
            giris = r["giris"]
            if b["Low"] <= stop:
                return {**r, "durum": "stop", "kapanis_zamani": t.isoformat(),
                        "kapanis_fiyati": float(stop), "sonuc_R": -1.0}
            if b["High"] >= hedef:
                return {**r, "durum": "hedef", "kapanis_zamani": t.isoformat(),
                        "kapanis_fiyati": float(hedef),
                        "sonuc_R": round((hedef - giris) / (giris - stop), 2)}
    if r["durum"] == "tetiklendi" and len(bars):
        r["son_fiyat"] = float(bars["Close"].iloc[-1])
    return r


def kontrol(durum: dict, simdi: datetime) -> list[dict]:
    """Bekleyen ve açık kurguları kontrol eder, olayları bildirir, kapananları döndürür."""
    izlenen = {s: k for s, k in durum["adaylar"].items() if k["durum"] in BEKLEYEN | ACIK}
    if not izlenen:
        return []
    veri = gun_ici(list(izlenen))
    kapananlar, mesajlar = [], []
    for s, k in izlenen.items():
        if s not in veri:
            continue
        r = simule_et(k, veri[s])
        yeni, eski = r["durum"], k["durum"]
        if yeni == "bekliyor":
            continue
        if eski == "bekliyor" and yeni in ("tetiklendi", "stop", "hedef"):
            g = r["giris"]
            rr = (k["hedef"] - g) / (g - k["stop"]) if g > k["stop"] else 0
            mesajlar.append(f"🟢 {ad(s)} TETİKLENDİ — {f(k['tetik'])} geçildi. Giriş ~{f(g)} · "
                            f"Stop {f(k['stop'])} · Hedef {f(k['hedef'])} · R/Ö {rr:.1f}")
        if yeni == "tetiklendi":
            # açık kalmaya devam; süre aşımı kontrolü
            k.update(durum="tetiklendi", giris=r["giris"], tetik_zamani=r["tetik_zamani"])
            acilis = datetime.fromisoformat(r["tetik_zamani"])
            if simdi - acilis > timedelta(days=MAX_ACIK_GUN * 7 / 5):
                son = r.get("son_fiyat", r["giris"])
                sonuc = round((son - r["giris"]) / (r["giris"] - k["stop"]), 2)
                k.update(durum="süre aşımı", kapanis_zamani=simdi.isoformat(),
                         kapanis_fiyati=son, sonuc_R=sonuc)
                mesajlar.append(f"⏱ {ad(s)} {MAX_ACIK_GUN} işlem günüdür hedefe/stopa "
                                f"ulaşmadı. Son fiyat {f(son)} ({sonuc:+.1f}R). Takip bırakıldı.")
            else:
                continue
        else:
            k.update(r)
            metin = {
                "iptal": f"❌ {ad(s)} tetiklenmeden stop seviyesine ({f(k['stop'])}) indi. "
                         f"Kurgu iptal.",
                "kaçtı": f"🚀 {ad(s)} boşlukla tetik seviyesinin çok üstüne çıktı "
                         f"({f(r['kapanis_fiyati'])}). Kovalamayın, kurgu kapatıldı.",
                "stop": f"🛑 {ad(s)} STOP oldu ({f(k['stop'])}). Sonuç: -1R.",
                "hedef": f"🎯 {ad(s)} HEDEFE ulaştı ({f(k['hedef'])}). "
                         f"Sonuç: +{r.get('sonuc_R', 0):.1f}R.",
            }[yeni]
            mesajlar.append(metin)
        kapananlar.append(k)
        del durum["adaylar"][s]
    if mesajlar:
        ab.telegram("\n\n".join(mesajlar))
    return kapananlar


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Emtia & Döviz botu")
    ap.add_argument("--saf", action="store_true", default=True)
    ap.add_argument("--yeni-kurallar", action="store_true")
    ap.add_argument("--test", action="store_true",
                    help="Saat kontrolü yok; hemen tara ve kontrol et; durum dosyasına yazma")
    args = ap.parse_args()
    pat.AYAR["saf"] = True
    if args.yeni_kurallar:
        pat.AYAR["yeni_kurallar"] = True
    ab.ETIKET = "Emtia & Döviz"

    simdi = datetime.now(TR)
    if not args.test and simdi.weekday() >= 5:
        print("Hafta sonu, çıkılıyor.")
        return

    durum = durum_oku() if not args.test else {"liste_tarihi": None, "adaylar": {}}
    kapananlar: list[dict] = []
    if args.test or (durum.get("liste_tarihi") != simdi.date().isoformat()
                     and simdi.hour >= LISTE_SAATI):
        kapananlar += liste_yap(durum, simdi)
    kapananlar += kontrol(durum, simdi)

    if args.test:
        print(f"Test bitti. İzlenen: {len(durum['adaylar'])}, kapanan: {len(kapananlar)}")
        return
    sonuc_kaydet(kapananlar)
    durum_yaz(durum)


if __name__ == "__main__":
    main()
