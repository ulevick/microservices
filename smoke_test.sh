#!/usr/bin/env bash
GW="${GW:-http://127.0.0.1:8000}"
U="vartotojas_$RANDOM"
U2="kitas_$RANDOM"
P="slaptas123"
JSON="Content-Type: application/json"
ok=0; fail=0

pass() { printf "  \033[32mOK\033[0m   %-50s %s\n" "$1" "$2"; ok=$((ok+1)); }
bad()  { printf "  \033[31mFAIL\033[0m %-50s gauta %s, laukta %s\n" "$1" "$2" "$3"; fail=$((fail+1)); }

expect() {
  local name="$1" want="$2"; shift 2
  local got
  got=$(curl -s -o /dev/null -w "%{http_code}" "$@")
  [ "$got" = "$want" ] && pass "$name" "$got" || bad "$name" "$got" "$want"
}

same() {
  local name="$1" want="$2" got="$3"
  [ "$got" = "$want" ] && pass "$name" "$got" || bad "$name" "$got" "$want"
}

token_for() {
  curl -s -X POST "$GW/auth/token" -H "$JSON" -d "{\"username\":\"$1\",\"password\":\"$2\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null
}

CRED="{\"username\":\"$U\",\"password\":\"$P\"}"
BAD_PW="{\"username\":\"$U\",\"password\":\"blogas\"}"
SHORT="{\"username\":\"trumpas\",\"password\":\"123\"}"
PROD="{\"name\":\"Kava 1kg\",\"price_cents\":1299}"
NEG_PRICE="{\"name\":\"X\",\"price_cents\":-100}"

echo "Gateway: $GW    naudotojas: $U"
echo
echo "PAGRINDINES FUNKCIJOS"
expect "1. registracija" 200 -X POST "$GW/auth/register" -H "$JSON" -d "$CRED"

TOKEN=$(token_for "$U" "$P")
same "2. prisijungimas (token gautas)" taip "$([ -n "$TOKEN" ] && echo taip || echo ne)"
AUTH="Authorization: Bearer $TOKEN"

PID=$(curl -s -X POST "$GW/catalog/products" -H "$AUTH" -H "$JSON" -d "$PROD" \
      | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
same "3. produkto pridejimas" taip "$([ -n "$PID" ] && echo taip || echo ne)"
expect "4. produktu perziura" 200 "$GW/catalog/products" -H "$AUTH"

ORDER="{\"product_id\":$PID,\"quantity\":2}"
expect "5. uzsakymo pridejimas" 200 -X POST "$GW/orders" -H "$AUTH" -H "$JSON" -d "$ORDER"
expect "6. uzsakymu perziura" 200 "$GW/orders" -H "$AUTH"
expect "7. atsijungimas" 200 -X POST "$GW/auth/logout" -H "$AUTH"

echo
echo "NEIGIAMI ATVEJAI"
expect "8. tokenas po atsijungimo negalioja" 401 "$GW/orders" -H "$AUTH"
expect "9. uzklausa be tokeno" 401 "$GW/orders"
expect "10. suklastotas tokenas" 401 "$GW/orders" -H "Authorization: Bearer aaa.bbb.ccc"
expect "11. pasikartojantis vardas" 400 -X POST "$GW/auth/register" -H "$JSON" -d "$CRED"
expect "12. neteisingas slaptazodis" 401 -X POST "$GW/auth/token" -H "$JSON" -d "$BAD_PW"
expect "13. per trumpas slaptazodis" 400 -X POST "$GW/auth/register" -H "$JSON" -d "$SHORT"

TOKEN2=$(token_for "$U" "$P")
AUTH2="Authorization: Bearer $TOKEN2"
NEG_QTY="{\"product_id\":$PID,\"quantity\":-5}"
NO_PROD="{\"product_id\":999999,\"quantity\":1}"
expect "14. neigiamas kiekis atmetamas" 422 -X POST "$GW/orders" -H "$AUTH2" -H "$JSON" -d "$NEG_QTY"
expect "15. neigiama kaina atmetama" 422 -X POST "$GW/catalog/products" -H "$AUTH2" -H "$JSON" -d "$NEG_PRICE"
expect "16. neegzistuojantis produktas" 400 -X POST "$GW/orders" -H "$AUTH2" -H "$JSON" -d "$NO_PROD"

echo
echo "IZOLIACIJA, APSAUGA, STEBESENA"
CRED2="{\"username\":\"$U2\",\"password\":\"$P\"}"
curl -s -X POST "$GW/auth/register" -H "$JSON" -d "$CRED2" >/dev/null
T2=$(token_for "$U2" "$P")
COUNT=$(curl -s "$GW/orders" -H "Authorization: Bearer $T2" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin)))" 2>/dev/null)
same "17. svetimu uzsakymu nesimato" 0 "$COUNT"
expect "18. gateway /health" 200 "$GW/health"
RID=$(curl -s -D - -o /dev/null "$GW/health" | grep -ci 'x-request-id')
same "19. X-Request-ID antraste" 1 "$RID"

echo
if [ $fail -eq 0 ]; then
  printf "\033[32mREZULTATAS: %d/%d OK\033[0m\n" "$ok" "$((ok+fail))"
else
  printf "\033[31mREZULTATAS: %d/%d OK, %d nepavyko\033[0m\n" "$ok" "$((ok+fail))" "$fail"
fi
exit $fail
