# 📄 Product Requirements Document (PRD)

**Project Name:** MariaDB Auto-Heal & Bottleneck Monitor

**Status:** Ready for Development

## 1. Ringkasan Eksekutif (Executive Summary)

Aplikasi ini adalah *background worker* ringan yang bertugas memonitor kesehatan MariaDB secara *real-time*. Tujuannya adalah mendeteksi secara dini lonjakan koneksi (*bottleneck*), mengidentifikasi *query* tunggal yang menjadi akar masalah (*holding lock*), secara otomatis mengeksekusi perintah `KILL` pada proses tersebut untuk mencegah *downtime*, dan mengirimkan *alert* yang rapi kepada tim administrator.

## 2. Arsitektur & Tech Stack

* **Bahasa Pemrograman:** Python 3.11+
* **Package Manager:** `uv` (untuk resolusi dependensi dan *build* Docker yang cepat)
* **Library Utama:** `aiomysql` (koneksi *asynchronous*), `asyncio` (*event-driven concurrency*)
* **Deployment:** Docker Container (Portable, *auto-restart*)
* **Environment Variables:** File `.env` (di- *load* saat eksekusi Docker run)

## 3. Spesifikasi Infrastruktur & Keamanan Database

* **Akses Jalur Darurat:** Menggunakan fitur `extra_port` (Port `3307`) pada MariaDB untuk memastikan aplikasi selalu dapat terhubung, sekalipun batas `max_connections` aplikasi utama telah penuh.
* **Koneksi Jaringan:** Aplikasi menembak langsung ke IP Host server MariaDB di jaringan lokal (bukan `localhost` internal Docker).
* **Keamanan Kredensial:** * Tidak ada *auto-provisioning* *user* melalui script aplikasi/Docker.
* *User* dibuat secara manual oleh administrator via MariaDB CLI.
* *User* dikunci secara spesifik ke IP mesin Docker yang menjalankan *monitoring* (`CREATE USER 'monitor_user'@'IP_DOCKER'`).
* Kredensial disimpan murni di file `.env` di *host* dan di- *inject* ke dalam Docker.



## 4. Logika Sistem (Key Flows)

### A. Polling & Deteksi (Low-Impact)

* Aplikasi melakukan *polling* setiap 1 detik.
* *Query* yang digunakan: `SHOW GLOBAL STATUS LIKE 'Threads_running'`.
* **Threshold:** Jika jumlah *threads running* **> 50**, sistem menganggap terjadi *bottleneck*.

### B. Identifikasi Pelaku Utama (The Blocker)

Sistem tidak mematikan *query* secara acak atau berdasarkan durasi terlama. Sistem mencari *thread* yang sedang menahan kunci tabel/baris (*holding lock*).

* **Prioritas 1 (Clean Approach):** Menjalankan *query* ke `sys.innodb_lock_waits` untuk mencari `blocking_pid`.
* **Prioritas 2 (Fallback):** Jika *schema* `sys` tidak tersedia/error, sistem otomatis menjalankan *query JOIN* ke `information_schema` (`innodb_lock_waits` dan `innodb_trx`).

### C. Eksekusi & Pemulihan

* Sistem mengeksekusi `KILL [blocking_pid]`.

### D. Sistem Alert (Anti-Spam)

Sistem menggunakan pola **State Toggle** (`is_bottleneck = boolean`) dibantu dengan `asyncio.Queue` untuk memisahkan proses pengecekan database dan proses pengiriman *alert* API (Telegram/WhatsApp).

* **Trigger Start:** Saat *bottleneck* terdeteksi dan *state* berubah `false -> true`, kirim 1x *alert* "🚨 Bottleneck Terdeteksi! [Jumlah koneksi]. Membunuh PID [ID] dengan query [Teks Query]".
* **Trigger Resolved:** Saat *threads running* turun hingga **< 10** dan *state* saat ini `true`, ubah *state* menjadi `false` dan kirim 1x *alert* "✅ Database kembali normal".

## 5. Struktur Deployment (Dockerfile)

Menggunakan pendekatan *multi-stage* atau *slim image* berbasis `uv`:

* *Base image* menggunakan `python:slim`.
* Menyalin eksekutor `uv` langsung dari *image* resmi `ghcr.io/astral-sh/uv`.
* Menggunakan `uv pip install --system aiomysql` untuk instalasi cepat tanpa *overhead virtual environment* di dalam *container*.
* Menyertakan instruksi `Restart=always` pada orkestrasi Docker untuk memastikan aplikasi memiliki "nyawa tak terbatas" jika terjadi *crash* tak terduga (misalnya *network timeout*).
