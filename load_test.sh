#!/bin/bash

URL="http://0.0.0.0:80"

for i in {1..1000}
do
  echo "Request #$i"
  curl -s -o /dev/null -w "%{http_code}\n" "$URL"
done

