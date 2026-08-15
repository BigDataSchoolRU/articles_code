#!/usr/bin/env bash
# прогон на Confluent Schema Registry 8.3.1, REST API v1
SR=http://localhost:8081
CT='Content-Type: application/vnd.schemaregistry.v1+json'

# 0. чистим subject от прошлого прогона: мягкое удаление, затем окончательное
curl -s -X DELETE $SR/subjects/orders-value > /dev/null
curl -s -X DELETE "$SR/subjects/orders-value?permanent=true" > /dev/null

# 1. регистрируем первую версию схемы заказа: идентификатор и сумма
curl -s -X POST -H "$CT" --data '{"schemaType":"AVRO","schema":"{\"type\":\"record\",\"name\":\"Order\",\"fields\":[{\"name\":\"id\",\"type\":\"string\"},{\"name\":\"amount\",\"type\":\"double\"}]}"}' \
  $SR/subjects/orders-value/versions
echo " <- id схемы v1"

# 2. проверяем вторую версию ДО регистрации: добавлено поле с default
curl -s -X POST -H "$CT" --data '{"schemaType":"AVRO","schema":"{\"type\":\"record\",\"name\":\"Order\",\"fields\":[{\"name\":\"id\",\"type\":\"string\"},{\"name\":\"amount\",\"type\":\"double\"},{\"name\":\"currency\",\"type\":\"string\",\"default\":\"RUB\"}]}"}' \
  $SR/compatibility/subjects/orders-value/versions/latest
echo " <- поле с default"

# 3. то же поле, но без default: реестр обязан отказать
curl -s -X POST -H "$CT" --data '{"schemaType":"AVRO","schema":"{\"type\":\"record\",\"name\":\"Order\",\"fields\":[{\"name\":\"id\",\"type\":\"string\"},{\"name\":\"amount\",\"type\":\"double\"},{\"name\":\"currency\",\"type\":\"string\"}]}"}' \
  $SR/compatibility/subjects/orders-value/versions/latest
echo " <- поле без default"

# 4. регистрируем совместимую версию, теперь в subject две версии
curl -s -X POST -H "$CT" --data '{"schemaType":"AVRO","schema":"{\"type\":\"record\",\"name\":\"Order\",\"fields\":[{\"name\":\"id\",\"type\":\"string\"},{\"name\":\"amount\",\"type\":\"double\"},{\"name\":\"currency\",\"type\":\"string\",\"default\":\"RUB\"}]}"}' \
  $SR/subjects/orders-value/versions
echo " <- id схемы v2"

# 5. текущий уровень проверки для subject и глобальный по умолчанию
curl -s $SR/config; echo " <- глобальный уровень"
