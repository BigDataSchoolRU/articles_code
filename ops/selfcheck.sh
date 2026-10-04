#!/usr/bin/env bash
# Функции проверок вызываются косвенно, через check "$@" — shellcheck этого не видит.
# shellcheck disable=SC2329
# Целостность репо демо-кода. Выход 0 — всё на месте. Запуск из корня репо: ops/selfcheck.sh
set -euo pipefail

cd "$(dirname "$0")/.."
fail=0

# Известные поломки опубликованного кода: правятся только вместе со статьёй (RUNBOOK §11).
KNOWN_BROKEN_PY="airflow_course/all_dags/07_dask_yandex.py airflow_course/article07/07_dask_yandex.py"

check() {
  local name=$1
  shift
  if "$@" >/dev/null 2>&1; then
    echo "OK   $name"
  else
    echo "FAIL $name"
    "$@" 2>&1 | sed 's/^/       /' | head -5
    fail=1
  fi
}

demos_complete() {
  # У каждого wiki/<slug>/ есть README.md, RUNBOOK.md и строка в оглавлении.
  local d s bad=0
  for d in wiki/*/; do
    s=$(basename "$d")
    [ -f "wiki/$s/README.md" ] || { echo "нет wiki/$s/README.md"; bad=1; }
    [ -f "wiki/$s/RUNBOOK.md" ] || { echo "нет wiki/$s/RUNBOOK.md"; bad=1; }
    grep -qF "($s/)" wiki/README.md || { echo "$s нет в wiki/README.md"; bad=1; }
  done
  return "$bad"
}

no_local_artifacts() {
  # selfcheck.sh демо, .status и run_output.txt — локальные артефакты стадии wiki-code.
  ! git ls-files | grep -v '^ops/selfcheck\.sh$' | grep -E '(^|/)(selfcheck\.sh|\.status|run_output\.txt|\.env)$'
}

python_compiles() {
  local f bad=0
  while IFS= read -r f; do
    case " $KNOWN_BROKEN_PY " in *" $f "*) continue ;; esac
    python3 -m py_compile "$f" 2>/dev/null || { echo "не компилируется: $f"; bad=1; }
  done < <(git ls-files '*.py')
  return "$bad"
}

check "у каждого демо есть README, RUNBOOK и строка в оглавлении" demos_complete
check "в git нет локальных артефактов прогона и .env" no_local_artifacts
check "Python компилируется (кроме известных поломок)" python_compiles

exit "$fail"
