# Rangkon

Sistem panggilan berkumpul melalui WhatsApp dengan dashboard penerimaan dan kehadiran,
diasingkan mengikut unit (lalai: **MK Rej, Bn 1, Bn 2, Bn 3**).

## Aliran kerja

1. **Pangkalan Data** (ikon di menu atas) — tambah / kemas kini ahli satu-satu (butang `+`, ikon pensel),
   atau muat naik Excel/CSV (lajur: `unit, pangkat, nama, no tentera, telefon`; contoh di
   `app/static/contoh-ahli.csv`). Nombor yang sudah wujud akan dikemas kini.
2. **Panggilan baru** — tajuk, lokasi, masa dan teks mesej (kod `{nama} {unit} {tajuk} {lokasi} {masa} {pautan}`).
3. **Hantar WhatsApp** — pilih unit. Setiap ahli menerima pautan peribadi.
4. Penerima **wajib TERIMA**: balas `TERIMA` / `TOLAK` di WhatsApp, atau tekan butang pada pautan.
   Hanya jawapan TERIMA dikira sebagai "Diterima". Status WhatsApp (dihantar / sampai / dibaca)
   ditunjuk berasingan sebagai maklumat.
5. **Kehadiran** — ahli tekan "Saya sudah sampai" pada pautan (dibuka 2 jam sebelum masa berkumpul),
   atau petugas guna **Kaunter kehadiran** (taip no. telefon), atau admin tanda terus di dashboard.
6. **Dashboard** — ringkasan keseluruhan + kad setiap unit (diterima / belum / tolak / hadir),
   jadual boleh ditapis ikut unit & status, auto-segar setiap 5 saat, muat turun CSV.

## Jalankan

```bash
cp .env.example .env    # tetapkan kata laluan admin dsb.
./run.sh                # http://localhost:8000
```

Ujian: `pip install -r requirements-dev.txt && pytest && ruff check app tests`

Pangkalan data SQLite disimpan di `data/rangkon.db` (tukar dengan `DATABASE_URL`).

## WhatsApp

`RANGKON_WHATSAPP_PROVIDER=simulate` (lalai) tidak menghantar mesej sebenar; dashboard
menunjukkan butang simulasi (delivered / read / TERIMA / TOLAK) untuk mencuba aliran penuh.

Untuk mesej sebenar guna **WhatsApp Business Cloud API** (Meta):

1. Cipta app di https://developers.facebook.com, tambah produk WhatsApp, dapatkan
   `WHATSAPP_TOKEN` (token kekal System User) dan `WHATSAPP_PHONE_NUMBER_ID`.
2. Tetapkan `RANGKON_WHATSAPP_PROVIDER=cloud` dan `RANGKON_PUBLIC_BASE_URL` (URL HTTPS awam aplikasi).
3. Webhook: URL `https://<domain>/webhook/whatsapp`, verify token = `WHATSAPP_VERIFY_TOKEN`,
   langgan medan `messages`. Tetapkan `WHATSAPP_APP_SECRET` supaya tandatangan disahkan.
4. Mesej pertama kepada ahli (di luar tetingkap 24 jam) mesti guna **template** yang diluluskan Meta.
   Tetapkan `WHATSAPP_TEMPLATE_NAME` / `WHATSAPP_TEMPLATE_LANG`; parameter badan template
   dihantar mengikut susunan `{{1}}=nama, {{2}}=tajuk, {{3}}=lokasi, {{4}}=masa, {{5}}=pautan`.
