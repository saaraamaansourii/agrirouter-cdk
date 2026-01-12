#!/bin/bash

cd "$(dirname "$BASH_SOURCE[0]")"/../
npx buf breaking proto --against './.git#subdir=proto'

if [[ $? != 0 ]]; then
    echo "❌ Protobuf changes are breaking! 
    Please make sure that you are not breaking running services with those changes.
    If you are sure that those changes are required, you can use 
    ALLOW_BREAK_PROTO=1 git commit ... to bypass this check.
    Use wisely!"
    exit 1
else
    echo "✅ ... No protobuf breaking changes detected"
fi

