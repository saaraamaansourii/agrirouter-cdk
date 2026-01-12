#!/bin/bash

cd "$(dirname "$BASH_SOURCE[0]")"/../
npx buf lint proto

if [[ $? != 0 ]]; then
    echo "❌ Protobuf linting failed! Please fix errors before committing."
    exit 1
else
    echo "✅ ... Protobuf lint done"
fi

