# Telegram Claude Agent

Asisten tim pribadi berbasis **Claude Code** yang dioperasikan lewat **Telegram**,
berjalan di **VPS** dalam **Docker**. Bisa riset, menulis & menjalankan kode,
mengolah file, dan edit video/audio via `ffmpeg` — sesuai perintah Anda.

> ⚠️ **Keamanan:** agent ini punya akses penuh (shell, tulis file) *di dalam container*.
> Container Docker adalah sandbox-nya. Bot dikunci hanya untuk Telegram ID Anda
> (`ALLOWED_USER_ID`). Jangan dibuka untuk publik.
>
> ℹ️ **Kebijakan:** memakai login langganan Claude untuk bot adalah wilayah abu-abu
> di kebijakan Anthropic. Untuk bot pribadi (hanya Anda) umumnya aman. Jika suatu
> saat dibuka ke banyak orang, pindah ke `ANTHROPIC_API_KEY`.

---

## 1. Siapkan 3 kredensial

| Variabel | Dari mana | Contoh |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Chat **@BotFather** → `/newbot` | `123456:ABC-DEF...` |
| `ALLOWED_USER_ID` | Chat **@userinfobot** → ambil angka ID | `123456789` |
| `CLAUDE_CODE_OAUTH_TOKEN` | Jalankan `claude setup-token` di mesin yang sudah login Claude | `sk-ant-oat01-...` |

> Token langganan butuh paket Claude Pro/Max/Team dan berlaku ~1 tahun.
> **Jangan** mengisi `ANTHROPIC_API_KEY` — kalau di-set, ia menimpa token langganan.

---

## 2. Push ke GitHub (dari komputer lokal)

Dari dalam folder proyek ini:

```bash
git init
```

```bash
git add . && git commit -m "Initial commit: telegram claude agent"
```

```bash
git branch -M main
```

Buat repo kosong di GitHub (mis. `telegram-claude-agent`), lalu:

```bash
git remote add origin https://github.com/USERNAME/telegram-claude-agent.git
```

```bash
git push -u origin main
```

> File `.env` **tidak** ikut ter-push (sudah masuk `.gitignore`). Aman.

---

## 3. Deploy di VPS

### a. Pastikan Docker terpasang
```bash
docker --version && docker compose version
```
Kalau belum ada, install cepat:
```bash
curl -fsSL https://get.docker.com | sh
```

### b. Clone repo
```bash
git clone https://github.com/USERNAME/telegram-claude-agent.git && cd telegram-claude-agent
```

### c. Buat file `.env`
```bash
cp .env.example .env && nano .env
```
Isi ketiga nilai dari langkah 1, lalu simpan (`Ctrl+O`, `Enter`, `Ctrl+X`).

### d. Build & jalankan
```bash
docker compose up -d --build
```

### e. Cek log
```bash
docker compose logs -f
```
Kalau muncul `Bot started.`, berarti sudah jalan. Buka Telegram, kirim `/start` ke bot Anda.

---

## 4. Pemakaian di Telegram

- Kirim pesan biasa = perintah ke agent (misal: *"Riset tren AI 2026 dan ringkas 5 poin"*).
- Kirim **file/video/foto** = disimpan ke folder kerja (`uploads/`), lalu perintahkan diolah
  (misal: *"potong video uploads/klip.mp4 dari detik 10 sampai 30"*).
- Perintah:
  - `/new` — mulai percakapan baru (lupakan konteks)
  - `/files` — lihat file hasil kerja
  - `/get <nama_file>` — ambil/unduh file hasil
  - `/help` — bantuan

---

## 5. Operasional

| Aksi | Perintah |
|---|---|
| Lihat log | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Stop | `docker compose down` |
| Update kode | `git pull && docker compose up -d --build` |
| Ambil semua file hasil ke host | `docker cp telegram-claude-agent:/app/workspace ./workspace-out` |
| Taruh file besar ke agent | `docker cp ./video.mp4 telegram-claude-agent:/app/workspace/` |

---

## Catatan teknis
- Paket: `claude-agent-sdk` (CLI Claude Code sudah ter-bundle, tidak perlu Node terpisah) + `python-telegram-bot`.
- Container berjalan sebagai user non-root `agent` (syarat mode `bypassPermissions`).
- Sesi & memori Claude disimpan di volume `claude-config`; file kerja di volume `workspace` — keduanya tetap ada walau container restart.
- File via bot Telegram: unduh maks ~20 MB, kirim (`/get`) maks ~50 MB. Untuk lebih besar pakai `docker cp`.
