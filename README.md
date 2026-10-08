# SmartFlow IDX — Aplikasi Screener Saham Smart Money & Bandarmology (Excel-Powered)

Aplikasi web analitik saham untuk mendeteksi akumulasi **Smart Money / Institusi / Bandarmology**, lonjakan volume (**Volume Spread Analysis / VSA**), **Ticket Size (Lot per Transaksi)**, dan **Foreign Flow** dari file **Excel (`.xlsx` / `.csv`)**.

---

## Fitur Utama
1. **5-Pillar Smart Money Scoring Engine (`0 - 100`)**:
   - **Pilar 1: Volume Spike & VSA (25 Poin)** — Rasio Volume terhadap `MA20` & posisi *Closing Range* candle.
   - **Pilar 2: Bandarmology / Broker Summary (30 Poin)** — Rasio akumulasi `Top 1 / Top 3 / Top 5 Broker` Pembeli vs Penjual dan akumulasi 5 hari bursa.
   - **Pilar 3: Ticket Size / Order Flow (15 Poin)** — Rata-rata lot per transaksi (`Volume_Lot / Frequency`) dibandingkan rata-rata 20 hari.
   - **Pilar 4: Institutional Foreign Flow (15 Poin)** — Persentase *Net Foreign Buy/Sell* harian & 5 hari terakhir.
   - **Pilar 5: Struktur Harga & Modal Bandar (15 Poin)** — Posisi harga terhadap `MA20` dan jarak terhadap rata-rata harga beli bandar (`Bandar_Avg_Buy`).
2. **Deteksi Trigger Otomatis**:
   - ⚡ `Markup Breakout`
   - 🐋 `Big Accumulation`
   - 🕵️ `Silent Accumulation`
   - 🌐 `Foreign Inflow Surge`
   - ⚠️ `Distribution Warning`
3. **Auto Trading Plan Calculator**:
   - Menghitung otomatis **Area Entry Ideal**, **Modal Rata-rata Bandar (5H)**, **Stop Loss (SL)**, **Target Price (TP1 & TP2)** sesuai fraksi harga BEI (IDX Tick Size), serta **Risk/Reward Ratio**.
4. **Standar Template Excel Siap Pakai**:
   - Tersedia di folder `data/sample_smart_money_idx.xlsx` (berisi simulasi 15 saham populer IDX selama 25 hari bursa) dan `data/blank_template_smart_money.xlsx`.

---

## Cara Menjalankan Aplikasi

1. Masuk ke direktori project:
   ```powershell
   cd C:\Users\enrik\.gemini\antigravity\scratch\smart-money-screener\backend
   ```
2. Jalankan server FastAPI:
   ```powershell
   python main.py
   ```
3. Buka browser dan akses:
   - **Dashboard Web UI**: `http://127.0.0.1:8000`
   - **Dokumentasi Swagger API**: `http://127.0.0.1:8000/docs`
