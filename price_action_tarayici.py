#!/usr/bin/env python3
"""
Price Action Tarayıcı
=====================
Yüzlerce enstrümanı günlük grafikte tarar, price action kurallarına göre
puanlar ve en iyi 5-10 adayı listeler. İŞLEM AÇMAZ; sadece izleme listesi üretir.

Kurulum (bir kez):
    pip install yfinance pandas numpy lxml

Kullanım:
    python price_action_tarayici.py --piyasa bist          (BIST'teki tüm hisseler, ~630)
    python price_action_tarayici.py --piyasa bist_likit    (büyük/likit ~60 hisse, hızlı)
    python price_action_tarayici.py --piyasa sp500 --adet 10
    python price_action_tarayici.py --piyasa nasdaq100 --saf
    python price_action_tarayici.py --piyasa kripto
    python price_action_tarayici.py --piyasa bist --saf     (saf price action: ortalama yok)
    python price_action_tarayici.py --dosya listem.txt      (her satırda bir Yahoo sembolü)

Çıktılar (betiğin çalıştığı klasöre):
    tarama_<piyasa>_<tarih>.csv   -> tüm geçen adaylar
    tarama_<piyasa>_<tarih>.html  -> en iyi N aday, gerekçeleri ve TradingView linkleriyle

Uyarı: Veri Yahoo Finance'ten gelir ve gecikmeli olabilir. Bu bir filtre aracıdır,
yatırım tavsiyesi değildir. Son kararı grafiğe bakarak siz verin.
"""

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# AYARLAR — kuralları buradan değiştirebilirsiniz
# ---------------------------------------------------------------------------
AYAR = {
    "periyot": "1y",            # ne kadar geçmiş veri çekilecek
    "aralik": "1d",             # zaman dilimi (günlük)
    "min_bar": 120,             # en az bu kadar mum yoksa enstrüman atlanır
    "pivot_k": 3,               # swing tepe/dip için iki yanda kaç mum bakılır
    "destek_tolerans_atr": 0.5, # aynı destek bölgesi sayılacak fiyat yakınlığı (ATR cinsinden)
    "min_dokunus": 2,           # yatay destek için en az kaç swing dip
    "geri_cekilme_min_atr": 1.0,
    "geri_cekilme_max_atr": 5.0,
    "hacim_kat": 1.5,           # kırılımda güçlü hacim: 20 günlük ortalamanın bu katı -> +2
    "hacim_kat_orta": 1.2,      # orta hacim: bu katın üstü -> +1
    "sikisma_oran": 0.8,        # ATR14 / ATR ortalaması bunun altındaysa "sıkışma"
    "min_rr": 2.0,              # hedeflenen en düşük risk/ödül
    "min_puan": 6,              # listeye girmek için en düşük puan
    "yapi_k": 5,                # trend yapısı için daha belirgin swing'ler (iki yanda 5 mum)
    "rol_tolerans_atr": 0.25,   # eski direncin yeniden test edildiği sayılacak yakınlık
    "max_stop_yuzde": 6.0,      # stop bundan uzaksa raporda uyarı çıkar
    "endeks_filtresi": True,    # piyasanın genel yönünü (endeksi) hesaba kat
    "endeks_ceza": 2,           # endeks düşüş yapısındaysa alış kurgularından düşülecek puan
    "bosluk_esik_yuzde": 4.0,   # bu kadar ve üstü aşağı boşluk "kötü haber boşluğu" sayılır
    "zirve_uzaklik_uyari": 15.0,  # 52 haftalık zirvenin bu kadar % altındaysa uyarı
    "yeni_kurallar": False,     # ABT sonrası eklenen kurallar: endeks filtresi, göreli güç,
                                # haber boşluğu, 52H uzaklık ve 5 dk kapanış teyidi (--yeni-kurallar)
    "saf": False,               # True: hareketli ortalama hiç kullanılmaz (--saf ile de açılır)
}

# Günlük ortalama işlem hacmi (fiyat x adet, 20 gün) alt sınırı — sığ ürünleri eler
MIN_ISLEM_DEGERI = {
    "bist": 20_000_000,   # TL
    "bist_likit": 20_000_000,
    "sp500": 5_000_000,   # USD
    "nasdaq100": 5_000_000,  # USD
    "kripto": 0,
    "dosya": 0,
}

# Borsa İstanbul'da işlem gören tüm hisseler (kaynak: İş Yatırım "Temel Değerler ve Oranlar"
# sayfası, Kasım 2026). Yeni halka arzlar ve kod değişiklikleri için ara sıra güncelleyin.
# Bulunamayan semboller atlanır ve raporda belirtilir.
BIST_SEMBOLLER = """
A1CAP A1YEN AAGYO ACSEL ADEL ADESE ADGYO AEFES AFYON AGESA AGHOL AGROT AGYO AHGAZ AHSGY
AKBNK AKCNS AKENR AKFGY AKFIS AKFYE AKGRT AKHAN AKMGY AKSA AKSEN AKSGY AKSUE AKYHO ALARK
ALBRK ALBTN ALCAR ALCTL ALFAS ALGYO ALKA ALKIM ALKLC ALTNY ALVES ANELE ANGEN ANHYT ANSGR
ARASE ARCLK ARDYZ ARENA ARFYE ARMGD ARSAN ARTMS ARZUM ASELS ASGYO ASTOR ASUZU ATAGY
ATAKP ATATP ATATR ATEKS ATLAS ATSYH AVGYO AVHOL AVOD AVPGY AVTUR AYCES AYDEM AYEN AYES
AYGAZ AZTEK BAGFS BAHKM BAKAB BALAT BALSU BANVT BARMA BASCM BASGZ BAYRK BEGYO BERA BESLR
BESTE BETAE BEYAZ BFREN BIENY BIGCH BIGEN BIGTK BIMAS BINBN BINHO BIOEN BIZIM BJKAS
BKRGY BLCYT BLUME BMSCH BMSTL BNTAS BOBET BORLS BORSK BOSSA BRISA BRKO BRKSN BRKVY BRLSM
BRMEN BRSAN BRYAT BSOKE BTCIM BUCIM BULGS BURCE BURVA BVSAN BYDNR CANTE CASA CATES CCOLA
CELHA CEMAS CEMTS CEMZY CEOEM CGCAM CIMSA CITAS CLEBI CMBTN CMENT CONSE COSMO CRDFA
CRFSA CUSAN CVKMD CWENE DAGI DAPGM DARDL DCTTR DENGE DERHL DERIM DESA DESPC DEVA DGATE
DGGYO DGNMO DIRIT DITAS DMRGD DMSAS DNISI DOAS DOCO DOFER DOFRB DOGUB DOHOL DOKTA DSTKF
DUNYH DURDO DURKN DYOBY DZGYO EBEBK ECILC ECOGR ECZYT EDATA EDIP EFOR EGEEN EGEGY EGEPO
EGGUB EGPRO EGSER EKDMR EKGYO EKIM EKIZ EKOS EKSUN ELITE EMKEL EMNIS EMPAE ENDAE ENERY
ENJSA ENKAI ENPRA ENSRI ENTRA EPLAS ERBOS ERCB EREGL ERSU ESCAR ESCOM ESEN ETILR ETYAT
EUHOL EUKYO EUPWR EUREN EUYO EYGYO FADE FENER FLAP FMIZP FONET FORMT FORTE FRIGO FRMPL
FROTO FZLGY GARAN GARFA GATEG GEDIK GEDZA GENIL GENKM GENTS GEREL GESAN GIPTA GLBMD
GLCVY GLRMK GLRYH GLYHO GMTAS GOKNR GOLDA GOLTS GOODY GOZDE GRNYO GRSEL GRTHO GSDDE
GSDHO GSRAY GUBRF GUNDG GWIND GZNMI HALKB HATEK HATSN HDFGS HEDEF HEKTS HKTM HLGYO HOROZ
HRKET HTTBT HUBVC HUNER HURGZ ICBCT ICUGS IDGYO IEYHO IHAAS IHEVA IHGZT IHLAS IHLGM
IHYAY IMASM INDES INFO INGRM INTEK INTEM INTET INVEO INVES ISATR ISBIR ISBTR ISCTR ISDMR
ISFIN ISGSY ISGYO ISKPL ISKUR ISMEN ISSEN ISVEA ISYAT IZENR IZFAS IZINV IZMDC JANTS
KAPLM KARCL KAREL KARSN KARTN KATMR KAYSE KBORU KCAER KCHOL KENT KERVN KFEIN KGYO KIMMR
KLGYO KLKIM KLMSN KLNMA KLRHO KLSER KLSYN KLYPV KMPUR KNFRT KOCMT KONKA KONTR KONYA
KOPOL KORDS KOTON KPEKS KRDMA KRDMB KRDMD KRGYO KRONT KRPLS KRSTL KRTEK KRVGD KSTUR
KTLEV KTSKR KUTPO KUVVA KUYAS KZBGY KZGYO LIDER LIDFA LILAK LINK LKMNH LMKDC LOGO LRSHO
LUKSK LXGYO LYDHO LYDYE MAALT MACKO MAGEN MAKIM MAKTK MANAS MARBL MARMR MARTI MASFN MAVI
MCARD MEDTR MEGAP MEGMT MEKAG MEPET MERCN MERIT MERKO METEN METRO MEYSU MGROS MHRGY
MIATK MMCAS MNDRS MNDTR MOBTL MOGAN MOPAS MPARK MRGYO MRSHL MSGYO MTRKS MTRYO MZHLD
NATEN NETAS NETCD NETGL NIBAS NTGAZ NTHOL NUGYO NUHCM OBAMS OBASE ODAS ODINE OFSYM ONCSM
ONRYT ORCAY ORGE ORMA ORZAX OSMEN OSTIM OTKAR OTTO OYAKC OYAYO OYLUM OYYAT OZATD OZGYO
OZKGY OZRDN OZSUB OZYSR PAGYO PAHOL PAMEL PAPIL PARSN PASEU PATEK PCILT PEKGY PENGD
PENTA PETKM PETUN PGSUS PINSU PKART PKENT PLTUR PNLSN PNSUT POLHO POLTK PRDGS PRKAB
PRKME PRZMA PSDTC PSGYO QNBFK QNBTR QUAGR QUICK RALYH RAYSG REEDR RGYAS RNPOL RODRG
RTALB RUBNS RUZYE RYGYO RYSAS SAFKR SAHOL SAMAT SANEL SANFM SANKO SARAE SARKY SASA SAYAS
SDTTR SEGMN SEGYO SEKFK SEKUR SELEC SELVA SERNT SEYKM SILVR SISE SKBNK SKTAS SKYLP SKYMD
SMART SMRTG SMRVA SNGYO SNICA SNPAM SODSN SOHOE SOKE SOKM SONME SRVGY SSAAT SUMAS SUNTK
SURGY SUWEN SVGYO TABGD TARKM TATEN TATGD TAVHL TBORG TCELL TCKRC TDGYO TEHOL TEKTU
TEZOL TGSAS THYAO TKFEN TKNKA TKNSA TLMAN TMPOL TMSN TNZTP TOASO TRALT TRCAS TRENJ TRGYO
TRHOL TRILC TRMET TSGYO TSKB TSPOR TTKOM TTRAK TUCLK TUKAS TUPRS TUREX TURGG TURSG UCAYM
UFUK ULAS ULKER ULUFA ULUSE ULUUN UNLU USAK USHOL VAKBN VAKFA VAKFN VAKKO VANGD VBTYZ
VERTU VERUS VESBE VESTL VEYAS VKFYO VKGYO VKING VRGYO VSNMD YAPRK YATAS YAYLA YBTAS
YEOTK YESIL YGGYO YIGIT YKBNK YKSLN YONGA YUNSA YYAPI YYLGD ZEDUR ZERGY ZGYO ZOREN ZRGYO
""".split()

# Büyük ve likit hisselerden oluşan kısa liste (--piyasa bist_likit)
BIST_LIKIT = """
AEFES AGHOL AKBNK AKSA AKSEN ALARK ARCLK ASELS ASTOR BIMAS BRSAN BRYAT CCOLA CIMSA DOAS
DOHOL EKGYO ENJSA ENKAI EREGL EUPWR FROTO GARAN GESAN GUBRF HALKB HEKTS ISCTR ISMEN
KARSN KCHOL KONTR KRDMD LOGO MAVI MGROS ODAS OTKAR OYAKC PETKM PGSUS SAHOL SASA SISE
SKBNK SOKM TAVHL TCELL THYAO TKFEN TOASO TSKB TTKOM TTRAK TUPRS ULKER VAKBN VESBE VESTL
YKBNK ZOREN
""".split()

# Nasdaq-100 bileşenleri (kaynak: slickcharts.com/nasdaq100, Kasım 2026; 101 sembol çünkü
# Alphabet'in iki hisse sınıfı var). Endeks her Aralık'ta yenilenir; yılda bir güncelleyin.
NASDAQ100_SEMBOLLER = """
NVDA AAPL MSFT AMZN GOOGL GOOG AVGO META TSLA ASML COST MU PLTR AMD NFLX CSCO AZN LRCX
AMAT INTC TMUS KLAC LIN SHOP PEP APP ISRG AMGN TXN QCOM BKNG GILD INTU PDD ADI HON PANW
ADBE CRWD ARM VRTX CEG SBUX ADP MELI CMCSA SNPS DASH MAR CDNS ORLY ABNB CTAS REGN MNST
MDLZ WBD MRVL CSX AEP PCAR ROST NXPI IDXX ADSK FTNT TRI PYPL EA BKR AXON MSTR FAST WDAY
EXC ROP XEL TTWO FANG DDOG CTSH MCHP CCEP PAYX CPRT GEHC KDP ODFL ZS TEAM VRSK KHC CSGP
DXCM CHTR ON BIIB LULU GFS TTD CDW
""".split()

KRIPTO_SEMBOLLER = """
BTC ETH BNB SOL XRP ADA DOGE TRX AVAX LINK DOT TON SHIB LTC BCH NEAR UNI APT
ICP ETC XLM FIL ATOM HBAR ARB OP INJ SUI AAVE MKR RNDR GRT ALGO SAND MANA AXS
""".split()


# ---------------------------------------------------------------------------
# Evren (taranacak sembol listesi)
# ---------------------------------------------------------------------------
def sp500_sembolleri() -> list[str]:
    import urllib.request
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tablo = pd.read_html(StringIO(r.read().decode("utf-8")))[0]
    return [s.replace(".", "-") for s in tablo["Symbol"].astype(str)]


def evren(piyasa: str, dosya: str | None) -> list[str]:
    if dosya:
        with open(dosya, encoding="utf-8") as f:
            return [s.strip() for s in f if s.strip() and not s.startswith("#")]
    if piyasa == "bist":
        return [f"{s}.IS" for s in BIST_SEMBOLLER]
    if piyasa == "bist_likit":
        return [f"{s}.IS" for s in BIST_LIKIT]
    if piyasa == "kripto":
        return [f"{s}-USD" for s in KRIPTO_SEMBOLLER]
    if piyasa == "sp500":
        return sp500_sembolleri()
    if piyasa == "nasdaq100":
        return list(NASDAQ100_SEMBOLLER)
    raise ValueError(f"Bilinmeyen piyasa: {piyasa}")


# Piyasa genel yönü için kullanılan endeks
ENDEKS = {"sp500": "SPY", "nasdaq100": "QQQ", "bist": "XU100.IS", "bist_likit": "XU100.IS",
          "kripto": "BTC-USD", "dosya": None}


def tradingview_linki(sembol: str) -> str:
    if sembol.endswith(".IS"):
        tv = "BIST:" + sembol[:-3]
    elif sembol.endswith("-USD"):
        tv = "BINANCE:" + sembol[:-4] + "USDT"
    else:
        tv = sembol.replace("-", ".")
    return f"https://www.tradingview.com/chart/?symbol={tv}"


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------
def veri_indir(semboller: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    sonuc: dict[str, pd.DataFrame] = {}
    for i in range(0, len(semboller), 100):
        parca = semboller[i:i + 100]
        print(f"  Veri indiriliyor: {i + 1}-{i + len(parca)} / {len(semboller)}")
        df = yf.download(parca, period=AYAR["periyot"], interval=AYAR["aralik"],
                         group_by="ticker", auto_adjust=True, threads=True,
                         progress=False)
        for s in parca:
            try:
                d = df[s] if isinstance(df.columns, pd.MultiIndex) else df
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(d):
                    sonuc[s] = d
            except KeyError:
                pass
    return sonuc


# ---------------------------------------------------------------------------
# Göstergeler ve yapı taşları
# ---------------------------------------------------------------------------
def atr(d: pd.DataFrame, n: int = 14) -> pd.Series:
    onceki = d["Close"].shift(1)
    tr = pd.concat([d["High"] - d["Low"],
                    (d["High"] - onceki).abs(),
                    (d["Low"] - onceki).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def pivotlar(seri: pd.Series, k: int, tepe: bool) -> list[tuple[int, float]]:
    """Swing tepe (tepe=True) ya da swing dip noktalarını (indeks, fiyat) döndürür."""
    v = seri.to_numpy()
    out = []
    for i in range(k, len(v) - k):
        pencere = v[i - k:i + k + 1]
        if (tepe and v[i] == pencere.max()) or (not tepe and v[i] == pencere.min()):
            out.append((i, float(v[i])))
    return out


def destek_bolgeleri(dipler: list[tuple[int, float]], tol: float) -> list[dict]:
    """Birbirine yakın swing dipleri bölgelerde toplar."""
    fiyatlar = sorted(p for _, p in dipler)
    bolgeler: list[list[float]] = []
    for p in fiyatlar:
        if bolgeler and p - bolgeler[-1][-1] <= tol:
            bolgeler[-1].append(p)
        else:
            bolgeler.append([p])
    return [{"alt": min(b), "ust": max(b), "dokunus": len(b)} for b in bolgeler]


def mum_sinyali(d: pd.DataFrame) -> tuple[str | None, int]:
    """Son mumda boğa yönlü price action sinyali arar. (ad, puan) döndürür."""
    o, h, l, c = d.iloc[-1][["Open", "High", "Low", "Close"]]
    po, ph, pl, pc = d.iloc[-2][["Open", "High", "Low", "Close"]]
    aralik = h - l
    if aralik <= 0:
        return None, 0
    govde = max(abs(c - o), 0.05 * aralik)
    alt_fitil = min(o, c) - l
    ust_fitil = h - max(o, c)

    if alt_fitil >= 2 * govde and ust_fitil <= 0.3 * aralik and (c - l) / aralik >= 0.66:
        return "Boğa pin bar", 2
    if pc < po and c > o and c >= po and o <= pc and (c - o) > (po - pc):
        return "Yutan boğa (engulfing)", 2
    if h <= ph and l >= pl:
        return "Inside bar (sıkışma, kırılım bekleniyor)", 1
    return None, 0


# ---------------------------------------------------------------------------
# Tek enstrüman analizi
# ---------------------------------------------------------------------------
def endeks_durumu(d: pd.DataFrame) -> dict:
    """Endeksin yapısını okur: düşüş yapısında (LH + LL) ya da son belirgin dibin altındaysa zayıf."""
    yk = AYAR["yapi_k"]
    c = float(d["Close"].iloc[-1])
    tepe = pivotlar(d["High"], yk, tepe=True)
    dip = pivotlar(d["Low"], yk, tepe=False)
    nedenler = []
    if len(tepe) >= 2 and len(dip) >= 2 and tepe[-1][1] < tepe[-2][1] and dip[-1][1] < dip[-2][1]:
        nedenler.append("düşen tepe ve dip yapısında")
    if dip and c < dip[-1][1]:
        nedenler.append("son belirgin dibin altında")
    getiri20 = c / float(d["Close"].iloc[-21]) - 1 if len(d) > 21 else 0.0
    return {"zayif": bool(nedenler), "aciklama": ", ".join(nedenler), "getiri20": getiri20}


def baglam(d: pd.DataFrame, endeks: dict | None) -> tuple[int, list[str], list[str]]:
    """Kurgudan bağımsız, hissenin genel durumu: endeks, göreli güç, haber boşluğu, 52H zirve."""
    puan, neden, uyari = 0, [], []
    c = float(d["Close"].iloc[-1])
    if endeks and AYAR["endeks_filtresi"]:
        if endeks["zayif"]:
            puan -= AYAR["endeks_ceza"]
            uyari.append(f"Endeks zayıf ({endeks['aciklama']}): alış kurguları daha riskli")
        if len(d) > 21:
            fark = (c / float(d["Close"].iloc[-21]) - 1) - endeks["getiri20"]
            if fark <= -0.05:
                puan -= 1; uyari.append(f"Son 20 günde endeksten %{-fark * 100:.0f} zayıf")
            elif fark >= 0.05:
                puan += 1; neden.append(f"Son 20 günde endeksten %{fark * 100:.0f} güçlü")
    # Kapanmamış büyük aşağı boşluk (bilanço / kötü haber izi), son ~2 ay
    son = d.tail(45)
    onceki_kapanis = d["Close"].shift(1).tail(45)
    bosluk = (son["Open"] / onceki_kapanis - 1) * 100
    buyukler = bosluk[bosluk <= -AYAR["bosluk_esik_yuzde"]]
    if len(buyukler):
        tarih = buyukler.index[-1]
        seviye = float(onceki_kapanis.loc[tarih])
        if c < seviye:
            puan -= 1
            uyari.append(f"{tarih:%d.%m} tarihli %{-buyukler.iloc[-1]:.1f} aşağı boşluk kapanmadı "
                         f"(boşluk öncesi {seviye:.2f}) — bilanço/kötü haber olabilir")
    yuksek = float(d["High"].tail(250).max())
    uzak = (1 - c / yuksek) * 100
    if uzak >= AYAR["zirve_uzaklik_uyari"]:
        uyari.append(f"52 haftalık zirvenin %{uzak:.0f} altında (büyük resim zayıf olabilir)")
    return puan, neden, uyari


@dataclass
class Aday:
    sembol: str
    kurgu: str
    durum: str            # "Sinyal var" | "İzle"
    puan: int
    fiyat: float
    giris: float
    stop: float
    hedef: float
    rr: float
    gerekceler: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    elenme: str = ""      # boşsa kuralları geçti; doluysa neden elendiği

    @property
    def stop_yuzde(self) -> float:
        return (self.giris - self.stop) / self.giris * 100 if self.giris else 0.0


def _stop_uyarisi(aday: Aday) -> None:
    if aday.stop_yuzde > AYAR["max_stop_yuzde"]:
        aday.uyarilar.append(f"Stop geniş (%{aday.stop_yuzde:.1f}), pozisyonu küçültün")


def analiz_et(sembol: str, d: pd.DataFrame, min_deger: float,
              endeks: dict | None = None) -> list[Aday]:
    """Sembolü değerlendirir; geçen ve elenen tüm kurguları döndürür (elenme alanı ile)."""
    if len(d) < AYAR["min_bar"]:
        return []
    d = d.copy()
    d["ATR"] = atr(d)
    d["SMA20"] = d["Close"].rolling(20).mean()
    d["SMA50"] = d["Close"].rolling(50).mean()
    d["HacimOrt"] = d["Volume"].rolling(20).mean().shift(1)

    son = d.iloc[-1]
    c, a = float(son["Close"]), float(son["ATR"])
    if not np.isfinite(a) or a <= 0:
        return []
    if (d["Close"] * d["Volume"]).tail(20).mean() < min_deger:
        return []

    n = len(d)
    saf = AYAR["saf"]
    tol = AYAR["destek_tolerans_atr"] * a
    k = AYAR["pivot_k"]
    tepeler = pivotlar(d["High"], k, tepe=True)          # küçük swing'ler: seviye/hedef
    dipler = pivotlar(d["Low"], k, tepe=False)
    yk = AYAR["yapi_k"]
    ytepe = pivotlar(d["High"], yk, tepe=True)           # belirgin swing'ler: trend yapısı
    ydip = pivotlar(d["Low"], yk, tepe=False)

    # --- Trend yapısı: belirgin swing'lerde HH + HL ve son HL bozulmamış olmalı ---
    hh_hl = (len(ytepe) >= 2 and len(ydip) >= 2
             and ytepe[-1][1] > ytepe[-2][1] and ydip[-1][1] > ydip[-2][1]
             and c > ydip[-1][1])
    yapi_guclu = hh_hl and len(ytepe) >= 3 and len(ydip) >= 3 \
        and ytepe[-2][1] > ytepe[-3][1] and ydip[-2][1] > ydip[-3][1]
    sma50_yukari = son["SMA50"] > d["SMA50"].iloc[-11]
    ma_trend = (not saf) and c > son["SMA50"] and sma50_yukari

    b_puan, b_neden, b_uyari = baglam(d, endeks) if AYAR["yeni_kurallar"] else (0, [], [])
    sonuc: list[Aday] = []

    # ======================= KURGU 1: Trend içi geri çekilme =======================
    if hh_hl or ma_trend:
        puan, neden, uyari = 0, [], []
        if hh_hl:
            puan += 2; neden.append("Yükselen yapı (belirgin swing'lerde HH + HL)")
        if yapi_guclu:
            puan += 1; neden.append("Yapı 3 swing boyunca korunuyor")
        if ma_trend:
            puan += 1; neden.append("Fiyat yükselen 50G ortalamanın üstünde")

        son_yuksek = float(d["High"].tail(20).max())
        derinlik = (son_yuksek - c) / a
        if AYAR["geri_cekilme_min_atr"] <= derinlik <= AYAR["geri_cekilme_max_atr"]:
            puan += 1; neden.append(f"Sağlıklı geri çekilme ({derinlik:.1f} ATR)")

        # Yatay destek bölgesi (son ~6 ay)
        yakin_dipler = [p for p in dipler if p[0] >= n - 130]
        bolgeler = [b for b in destek_bolgeleri(yakin_dipler, tol)
                    if b["dokunus"] >= AYAR["min_dokunus"] and b["alt"] <= c]
        son3_dip = float(d["Low"].tail(3).min())
        son3_kapanis_min = float(d["Close"].tail(3).min())
        destek = None
        for b in sorted(bolgeler, key=lambda b: b["ust"], reverse=True):
            if son3_dip <= b["ust"] + 0.3 * a and c >= b["alt"]:
                destek = b
                break
        if destek:
            puan += 2
            neden.append(f"Yatay destekte ({destek['alt']:.2f}-{destek['ust']:.2f}, "
                         f"{destek['dokunus']} dokunuş)")
        dinamik = (not saf) and \
            (son3_dip <= son["SMA20"] * 1.01 or son3_dip <= son["SMA50"] * 1.01) \
            and c > son["SMA50"]
        if dinamik:
            puan += 1; neden.append("20G/50G ortalamadan destek aldı")

        # Rol değişimi: eski swing tepe NET kırılmış (sonrasında +0.5 ATR üstünde kapanış),
        # fiyat şimdi geri gelip o seviyeyi test ediyor ve üstünde kapanıyor.
        rol = None
        rtol = AYAR["rol_tolerans_atr"] * a
        for i, p in sorted(tepeler, key=lambda t: t[1], reverse=True):
            if not (n - 130 <= i < n - 10 and p < c):
                continue
            kirildi = bool((d["Close"].iloc[i + 1:n - 3] > p + 0.5 * a).any())
            if kirildi and abs(son3_dip - p) <= rtol and son3_kapanis_min >= p - 0.1 * a:
                rol = p
                break
        if rol is not None:
            if destek and destek["alt"] - tol <= rol <= destek["ust"] + tol:
                puan += 1; neden.append(f"Destek, eski dirençle çakışıyor (~{rol:.2f})")
            else:
                puan += 2; neden.append(f"Kırılan direnç desteğe döndü (~{rol:.2f})")

        sinyal, sp = mum_sinyali(d)
        if sinyal:
            puan += sp; neden.append(sinyal)
            if son["Volume"] > son["HacimOrt"]:
                puan += 1; neden.append("Sinyal mumunda hacim ortalamanın üstünde")
        else:
            aralik = son["High"] - son["Low"]
            if aralik > 0 and (son["High"] - max(son["Open"], c)) / aralik >= 0.5:
                puan -= 1; uyari.append("Son mumda uzun üst fitil (satış baskısı)")

        giris = float(son["High"]) + 0.05 * a
        stop_taban = min(son3_dip, destek["alt"]) if destek else son3_dip
        stop = stop_taban - 0.2 * a
        # Hedef: trendin son BELİRGİN tepesi (küçük ara tepeler değil).
        # Üstte belirgin tepe yoksa ölçülü hareket: son HL + önceki itki boyu.
        ust_belirgin = [p for _, p in ytepe[-6:] if p > giris + 0.5 * a]
        olculu = None
        if len(ytepe) >= 1 and len(ydip) >= 2:
            olculu = ydip[-1][1] + (ytepe[-1][1] - ydip[-2][1])
        if ust_belirgin:
            hedef, hedef_not = min(ust_belirgin), "son belirgin swing tepe"
        elif olculu and olculu > giris + 0.5 * a:
            hedef, hedef_not = olculu, "ölçülü hareket (zirve bölgesi)"
        else:
            hedef, hedef_not = giris + 3 * a, "zirve bölgesi, 3 ATR"
        risk = giris - stop
        rr = (hedef - giris) / risk if risk > 0 else 0.0
        neden.append(f"Hedef: {hedef_not}")
        ara = [p for _, p in tepeler[-15:] if giris + 0.3 * a < p < hedef - 0.3 * a]
        if ara:
            uyari.append(f"Hedefe giderken küçük direnç var (~{min(ara):.2f})")
        if not sinyal:
            uyari.append("Dönüş mumu yok: giriş için sinyal mumu bekleyin")
        puan += b_puan; neden += b_neden; uyari += b_uyari

        aday = Aday(sembol, "Geri çekilme", "Sinyal var" if sinyal else "İzle",
                    puan, c, giris, stop, hedef, rr, neden, uyari)
        _stop_uyarisi(aday)
        if not (destek or dinamik or rol is not None or sinyal):
            aday.elenme = "Destek ya da dönüş mumu yok"
        elif rr < AYAR["min_rr"]:
            aday.elenme = f"R/Ö {rr:.1f} < {AYAR['min_rr']:.1f} (hedef çok yakın)"
        elif puan < AYAR["min_puan"]:
            aday.elenme = f"Puan {puan} < {AYAR['min_puan']}"
        sonuc.append(aday)

    # ============================ KURGU 2: Kırılım ============================
    onceki_zirve = float(d["Close"].iloc[-21:-1].max())
    if c > onceki_zirve:
        puan, neden, uyari = 2, ["20 günlük kapanış zirvesi kırıldı"], []
        hacim_kat = son["Volume"] / son["HacimOrt"] if son["HacimOrt"] > 0 else 0
        if hacim_kat >= AYAR["hacim_kat"]:
            puan += 2; neden.append(f"Güçlü hacim teyidi ({hacim_kat:.1f}x ortalama)")
        elif hacim_kat >= AYAR["hacim_kat_orta"]:
            puan += 1; neden.append(f"Hacim ortalamanın üstünde ({hacim_kat:.1f}x)")
        else:
            uyari.append(f"Hacim zayıf ({hacim_kat:.1f}x ortalama)")
        atr_ort = d["ATR"].iloc[-120:-5].mean()
        if d["ATR"].iloc[-6] / atr_ort < AYAR["sikisma_oran"]:
            puan += 1; neden.append("Kırılım öncesi sıkışma (düşük volatilite)")
        if ma_trend:
            puan += 1; neden.append("Yükselen 50G ortalamanın üstünde")
        if hh_hl:
            puan += 1; neden.append("Yükselen yapı (HH + HL)")
        testler = [p for i, p in tepeler if n - 130 <= i < n - 3 and abs(p - onceki_zirve) <= tol]
        if len(testler) >= 2:
            puan += 1; neden.append(f"Kırılan direnç {len(testler)} kez test edilmişti")
        aralik = son["High"] - son["Low"]
        if aralik > 0 and (c - son["Low"]) / aralik >= 0.75:
            puan += 1; neden.append("Mum güçlü kapandı (üst çeyrekte)")
        if saf:
            if c > onceki_zirve + 2 * a:
                puan -= 2; uyari.append("Kırılım seviyesinden çok uzaklaşmış")
        elif c > son["SMA20"] + 3 * a:
            puan -= 2; uyari.append("Ortalamadan çok uzaklaşmış")

        giris = c
        stop = float(son["Low"]) - 0.2 * a
        if giris - stop < 0.5 * a:          # çok dar stop gürültüde patlar
            stop = giris - 0.5 * a
        hedef = giris + AYAR["min_rr"] * (giris - stop)
        neden.append(f"Hedef: ölçülü {AYAR['min_rr']:.0f}R")
        puan += b_puan; neden += b_neden; uyari += b_uyari
        aday = Aday(sembol, "Kırılım", "Sinyal var", puan, c, giris, stop, hedef,
                    AYAR["min_rr"], neden, uyari)
        _stop_uyarisi(aday)
        if puan < AYAR["min_puan"]:
            aday.elenme = f"Puan {puan} < {AYAR['min_puan']}"
        sonuc.append(aday)

    return sonuc


# ---------------------------------------------------------------------------
# Rapor
# ---------------------------------------------------------------------------
def _tablo(adaylar: list[Aday]) -> str:
    if not adaylar:
        return "<p class='k'>Bu bölümde aday yok.</p>"
    satirlar = []
    for i, a in enumerate(adaylar, 1):
        uy = "".join(f"<li class='u'>{html.escape(u)}</li>" for u in a.uyarilar)
        satirlar.append(f"""
        <tr>
          <td>{i}</td>
          <td><a href="{tradingview_linki(a.sembol)}" target="_blank"><b>{html.escape(a.sembol)}</b></a></td>
          <td>{a.kurgu}</td><td class="p">{a.puan}</td>
          <td>{a.fiyat:.2f}</td><td>{a.giris:.2f}</td>
          <td>{a.stop:.2f} <span class="k">(-%{a.stop_yuzde:.1f})</span></td>
          <td>{a.hedef:.2f}</td><td>{a.rr:.1f}</td>
          <td><ul>{''.join(f'<li>{html.escape(g)}</li>' for g in a.gerekceler)}{uy}</ul></td>
        </tr>""")
    return ("<table><tr><th>#</th><th>Sembol</th><th>Kurgu</th><th>Puan</th><th>Son fiyat</th>"
            "<th>Giriş (öneri)</th><th>Stop</th><th>Hedef</th><th>R/Ö</th><th>Gerekçe</th></tr>"
            + "".join(satirlar) + "</table>")


def html_rapor(sinyal: list[Aday], izle: list[Aday], piyasa: str, taranan: int,
               eksik: list[str], yol: str) -> None:
    mod = "SAF price action" if AYAR["saf"] else "standart"
    eksik_not = (f"<p class='k'>Verisi alınamayan {len(eksik)} sembol: "
                 f"{html.escape(', '.join(eksik[:40]))}{' …' if len(eksik) > 40 else ''}</p>"
                 if eksik else "")
    icerik = f"""<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">
<title>Price Action Taraması — {piyasa.upper()}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:24px;color:#222}}
 table{{border-collapse:collapse;width:100%;font-size:14px;margin-bottom:28px}}
 th,td{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
 th{{background:#f4f4f4}} .p{{font-weight:bold;color:#0a6}} .k{{color:#888;font-size:12px}}
 .u{{color:#c0392b}} ul{{margin:0;padding-left:18px}}
</style></head><body>
<h2>Price Action Taraması — {piyasa.upper()} ({mod})</h2>
<p>{datetime.now():%d.%m.%Y %H:%M} · {taranan} enstrüman tarandı ·
{len(sinyal)} sinyalli aday · {len(izle)} izlenecek</p>
<h3>Sinyal var</h3>
<p class="k">Geri çekilmede dönüş mumu oluşmuş ya da kırılım gerçekleşmiş adaylar.</p>
{_tablo(sinyal)}
<h3>İzle — sinyal bekleniyor</h3>
<p class="k">Yapı ve seviye uygun, ama henüz dönüş mumu yok. Giriş seviyesi yalnızca bilgi amaçlı.</p>
{_tablo(izle)}
{eksik_not}
<p class="k">Bu liste bir filtre çıktısıdır, yatırım tavsiyesi değildir. Veri gecikmeli olabilir.
Giriş seviyesi geri çekilmede son mumun tepesinin hemen üstü, kırılımda son kapanıştır.</p>
</body></html>"""
    with open(yol, "w", encoding="utf-8") as f:
        f.write(icerik)


def _satir(a: Aday) -> dict:
    return {"sembol": a.sembol, "kurgu": a.kurgu, "durum": a.durum, "puan": a.puan,
            "fiyat": round(a.fiyat, 4), "giris": round(a.giris, 4), "stop": round(a.stop, 4),
            "stop_yuzde": round(a.stop_yuzde, 2), "hedef": round(a.hedef, 4),
            "rr": round(a.rr, 2), "gerekceler": " | ".join(a.gerekceler),
            "uyarilar": " | ".join(a.uyarilar), "elenme": a.elenme}


def tara(piyasa: str, dosya: str | None = None, adet: int = 10) -> dict:
    """Taramayı yapar; sonuçları sözlük olarak döndürür (başka betiklerden de çağrılır)."""
    anahtar = "dosya" if dosya else piyasa
    semboller = evren(piyasa, dosya)
    print(f"{len(semboller)} sembol taranacak ({anahtar}).")
    veri = veri_indir(semboller)
    eksik = [s for s in semboller if s not in veri]

    endeks = None
    endeks_sembol = ENDEKS.get(anahtar)
    if endeks_sembol and AYAR["endeks_filtresi"] and AYAR["yeni_kurallar"]:
        try:
            ed = veri_indir([endeks_sembol]).get(endeks_sembol)
            if ed is not None and len(ed) > AYAR["min_bar"]:
                endeks = endeks_durumu(ed)
                endeks["sembol"] = endeks_sembol
                print(f"Endeks ({endeks_sembol}): "
                      f"{'ZAYIF — ' + endeks['aciklama'] if endeks['zayif'] else 'normal'}")
        except Exception as e:
            print(f"Endeks verisi alınamadı: {e}", file=sys.stderr)

    tum: list[Aday] = []
    for s, d in veri.items():
        try:
            tum.extend(analiz_et(s, d, MIN_ISLEM_DEGERI[anahtar], endeks))
        except Exception as e:  # tek sembol hatası taramayı durdurmasın
            print(f"  {s} atlandı: {e}", file=sys.stderr)

    gecen = [a for a in tum if not a.elenme]
    elenen = [a for a in tum if a.elenme]
    # Aynı sembol iki kurguya da uyduysa yüksek puanlıyı tut
    en_iyi: dict[str, Aday] = {}
    for a in gecen:
        if a.sembol not in en_iyi or a.puan > en_iyi[a.sembol].puan:
            en_iyi[a.sembol] = a
    sirali = sorted(en_iyi.values(), key=lambda a: (a.puan, a.rr), reverse=True)
    return {"sinyal": [a for a in sirali if a.durum == "Sinyal var"][:adet],
            "izle": [a for a in sirali if a.durum == "İzle"][:adet],
            "sirali": sirali, "elenen": elenen, "veri": veri, "eksik": eksik,
            "endeks": endeks}


def seans_uyarisi(piyasa: str) -> str | None:
    """Seans açıkken son günlük mum yarımdır: hacim düşük, mum şekli yanıltıcı görünür."""
    from zoneinfo import ZoneInfo
    if piyasa == "kripto":
        return ("Kripto 7/24 işlem görür: son günlük mum henüz kapanmadı (UTC 00:00'da kapanır). "
                "Mum ve hacim kuralları için kapanıştan hemen sonra tarayın.")
    saatler = {"sp500": ("America/New_York", (9, 30), (16, 0)),
               "nasdaq100": ("America/New_York", (9, 30), (16, 0)),
               "bist": ("Europe/Istanbul", (10, 0), (18, 10)),
               "bist_likit": ("Europe/Istanbul", (10, 0), (18, 10))}
    if piyasa not in saatler:
        return None
    tz, ac, kapa = saatler[piyasa]
    simdi = datetime.now(ZoneInfo(tz))
    if simdi.weekday() < 5 and ac <= (simdi.hour, simdi.minute) < kapa:
        return ("Seans şu an açık: son mum yarım, hacmi düşük ve şekli yanıltıcı görünebilir. "
                "En sağlıklı sonuç için kapanıştan sonra tarayın.")
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Price action tarayıcı")
    ap.add_argument("--piyasa", choices=["bist", "bist_likit", "sp500", "nasdaq100", "kripto"], default="bist")
    ap.add_argument("--dosya", help="Sembol listesi dosyası (her satırda bir Yahoo sembolü)")
    ap.add_argument("--adet", type=int, default=10, help="Her bölümde listelenecek aday sayısı")
    ap.add_argument("--saf", action="store_true",
                    help="Saf price action: hareketli ortalama kullanılmaz")
    args = ap.parse_args()
    if args.saf:
        AYAR["saf"] = True
    piyasa = "dosya" if args.dosya else args.piyasa
    print("Mod: SAF price action (ortalama yok)" if AYAR["saf"] else "Mod: standart")

    uyari = seans_uyarisi(piyasa)
    if uyari:
        print("UYARI: " + uyari)
    t = tara(args.piyasa, args.dosya, args.adet)
    sinyal, izle, sirali, elenen, veri, eksik = (
        t["sinyal"], t["izle"], t["sirali"], t["elenen"], t["veri"], t["eksik"])

    tarih = datetime.now().strftime("%Y%m%d_%H%M") + ("_saf" if AYAR["saf"] else "")
    on = f"tarama_{piyasa}_{tarih}"
    pd.DataFrame([_satir(a) for a in sirali]).to_csv(f"{on}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([_satir(a) for a in sorted(elenen, key=lambda a: -a.puan)]) \
        .to_csv(f"{on}_elenen.csv", index=False, encoding="utf-8-sig")
    html_rapor(sinyal, izle, piyasa, len(veri), eksik, f"{on}.html")

    print(f"\n{len(veri)} enstrüman analiz edildi, {len(sirali)} aday kuralları geçti "
          f"({len(elenen)} kurgu elendi).")
    for baslik, liste in (("SİNYAL VAR", sinyal), ("İZLE (sinyal bekleniyor)", izle)):
        print(f"\n{baslik}:")
        for i, a in enumerate(liste, 1):
            uy = "  ⚠ " + "; ".join(a.uyarilar) if a.uyarilar else ""
            print(f" {i:2}. {a.sembol:<10} {a.kurgu:<13} puan {a.puan:2}  giriş {a.giris:.2f}  "
                  f"stop {a.stop:.2f} (-%{a.stop_yuzde:.1f})  hedef {a.hedef:.2f}  "
                  f"R/Ö {a.rr:.1f}{uy}")
        if not liste:
            print("  (yok)")
    kir = [a for a in elenen if a.kurgu == "Kırılım"]
    if kir:
        print(f"\nEşiğe takılan kırılımlar: {len(kir)} "
              f"(en yüksek puan {max(a.puan for a in kir)}) — ayrıntı: {on}_elenen.csv")
    print(f"\nRapor: {on}.html\nGeçenler: {on}.csv\nElenenler: {on}_elenen.csv")


if __name__ == "__main__":
    main()
