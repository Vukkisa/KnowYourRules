#!/bin/bash
# usage: run_linux.sh <label> <memory> <cpus> -> eval/deployment/stage7b2/linux/<label>.json (+ .exit). One container, one process; nothing else runs meanwhile.
cd "$(dirname "$0")/../../../.."
L=$1; MEM=$2; CPUS=$3
OUT=eval/deployment/stage7b2/linux
docker run --rm --name kyr-$L --memory=$MEM --memory-swap=$MEM --cpus=$CPUS \
  -v kyr-deps:/deps:ro -v kyr-data:/data -v "$PWD":/app:ro \
  -e PYTHONPATH=/deps -e PYTHONPYCACHEPREFIX=/tmp/pyc -e TG_DB_DIR=/data/index -e RAG_VECTOR_SEARCH=exact \
  -e EMBEDDING_PROVIDER=openai_compatible -e EMBEDDING_API_URL=http://127.0.0.1:9/v1 -e EMBEDDING_API_KEY=unused -e EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5 \
  -e OLLAMA_ENABLED=false -e GROQ_API_KEY=unused-no-calls -e KYR_NO_NETWORK=1 -e KYR_NSEQ=${KYR_NSEQ:-40} -e KYR_CONC=${KYR_CONC:-1} \
  python:3.11-slim python /app/eval/deployment/stage7b2/linux/linux_child.py > $OUT/$L.raw 2> $OUT/$L.err
echo $? > $OUT/$L.exit
tail -1 $OUT/$L.raw > $OUT/$L.json
