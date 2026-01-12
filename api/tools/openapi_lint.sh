#!/bin/bash

OPENAPI_REGEX="openapi/.*\.(json|yaml|yml)$"
STAGED_FILES=$(git diff --name-only --cached --diff-filter=AM | grep -E "$OPENAPI_REGEX" )
MODIFIED_FILES=$(git ls-files --modified | grep -E "$OPENAPI_REGEX" )
FILES=()

for file in $STAGED_FILES
do
  FILES+=($file)
done

for file in $MODIFIED_FILES
do
  FILES+=($file)
done

for i in "${FILES[@]}"
do
  echo "Linting file: $i"
# Since we cannot distinguish root spec from extracted
# bits, we need to disable undknown format rule to avoid false warnings
# This can be turned back on if all root files have matching name
  npx spectral lint --ignore-unknown-format $i

  if [[ $? != 0 ]]; then
    echo "❌ OpenAPI linting failed! Please fix errors before committing:"
    npx spectral lint --ignore-unknown-format -f text $i
    exit 1
  fi

done

echo "✅ ... OpenAPI lint done"

