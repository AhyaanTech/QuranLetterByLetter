# Roadmap

## Foundation
- [ ] Surah metadata — populate name_en, name_ar, name_translation, revelation_type, bismillah_pre
- [ ] CI auto-deploy to homelab — on push to main, trigger data rebuild and deploy to K8s cluster

## Core Features
- [x] SQLite data pipeline (build_db.py, build_letters.py)
- [x] Letter breakdown with 34 diacritic flags (338,281 letters)
- [x] PostgreSQL + Hasura GraphQL layer (Docker Compose + K8s)
- [x] Homelab K8s deployment (Postgres, Hasura, Explorer, Loader Job)
- [x] GHCR Docker image + release workflow

## Polish
- [x] Integrity validation tests (round-trip letters→words→ayahs)
- [ ] Cloudflare Tunnel for external access (quranapi.ahyaantech.com)
- [ ] Hasura metadata sync (track tables, relationships, permissions as code)

## Future Ideas
- [ ] Tajweed color metadata integration (from qpc-hafs-tajweed.db)
- [ ] Full-text search across Quran text
- [ ] Mushaf page rendering with letter highlighting
- [ ] Flutter Mushaf app integration (consume Hasura GraphQL)
