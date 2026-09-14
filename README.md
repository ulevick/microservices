# Monolitas perdarytas į mikroservisus

Laboratorinis darbas. Duotas monolitinis FastAPI servisas išskaidytas į keturis
mikroservisus su API gateway.

## Servisai

| Servisas | Portas | Ką daro |
|---|---|---|
| gateway | 8000 | priima visas užklausas, tikrina token'ą, nukreipia toliau |
| auth | 8001 | registracija, prisijungimas, atsijungimas |
| catalog | 8002 | produktai |
| order | 8003 | užsakymai |

Kiekvienas turi savo SQLite duomenų bazę. Monolite buvo viena `manoDB.db`.

## Paleidimas

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./start_all.sh
```

Swagger: http://127.0.0.1:8000/docs

Sustabdyti — `./stop_all.sh`. Galima ir rankomis, keturiuose terminaluose:

```bash
cd auth    && uvicorn main:app --port 8001
cd catalog && uvicorn main:app --port 8002
cd order   && uvicorn main:app --port 8003
cd gateway && uvicorn main:app --port 8000
```

## Maršrutai

Išoriniai adresai nepasikeitė, tik dabar už jų stovi keli servisai:

```
POST /auth/register      POST /catalog/products     POST /orders
POST /auth/token         GET  /catalog/products     GET  /orders
POST /auth/logout
```

## Pastabos

**Token'ai.** Gateway pats JWT nedekoduoja — klausia auth serviso per `/verify`.
Taip slaptas raktas lieka vienoje vietoje. Žemesniems servisams gateway perduoda
`X-User` antraštę.

**Atsijungimas.** Monolite atšaukti token'ai buvo laikomi Python aibėje, tad po
serviso perkrovimo atsijungimas nustodavo galioti. Perkėliau į duomenų bazę.

**Užsakymai ir produktai.** Kadangi bazės atskiros, `JOIN` nebeįmanomas. Order
servisas prieš įrašydamas užsakymą paklausia catalog, ar produktas egzistuoja, ir
išsisaugo kainą bei pavadinimą. Dėl to užsakymų sąrašui catalog nebereikalingas, o
pasikeitus kainai seni užsakymai nepasikeičia.

**Ką dar pataisiau monolite.** Nebuvo importuotas `JWTError`, todėl su blogu
token'u grįždavo 500 vietoj 401. Produkto kūrimas buvo be autentifikacijos.
Užsakymai neturėjo `username`, tad visi matė visų užsakymus. Taip pat pridėjau
kiekio ir kainos validaciją.

## Testavimas

```bash
./smoke_test.sh
```

Patikrina visas 7 funkcijas ir neigiamus atvejus (blogas slaptažodis, užklausa be
token'o, token'as po atsijungimo, neegzistuojantis produktas ir kt.).

Postmanui yra `postman_collection.json`.
