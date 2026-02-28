#!/bin/bash
# <bitbar.title>proxy-doctor</bitbar.title>
# <bitbar.version>v0.1.0</bitbar.version>
# <bitbar.author>Jiansen He</bitbar.author>
# <bitbar.author.github>Jiansen</bitbar.author.github>
# <bitbar.desc>Diagnose proxy issues affecting AI coding tools</bitbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>false</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>

# Refresh every 5 minutes (encoded in filename: proxy-doctor.5m.sh)

PYTHON="${PROXY_DOCTOR_PYTHON:-python3}"
PROXY_DOCTOR_SRC="${PROXY_DOCTOR_SRC:-}"

run_check() {
    if [ -n "$PROXY_DOCTOR_SRC" ]; then
        PYTHONPATH="$PROXY_DOCTOR_SRC" "$PYTHON" -m proxy_doctor.cli check --json 2>/dev/null
    elif "$PYTHON" -c "import proxy_doctor" 2>/dev/null; then
        "$PYTHON" -m proxy_doctor.cli check --json 2>/dev/null
    else
        echo '{"status":"error","diagnosis":{"root_cause":"proxy-doctor not installed"}}'
    fi
}

result=$(run_check)
status=$(echo "$result" | "$PYTHON" -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null)

case "$status" in
    healthy)
        echo "✓ | sfSymbol=checkmark.circle.fill color=green"
        ;;
    unhealthy)
        echo "✗ | sfSymbol=exclamationmark.triangle.fill color=red"
        ;;
    warning)
        echo "! | sfSymbol=exclamationmark.circle.fill color=orange"
        ;;
    *)
        echo "? | sfSymbol=questionmark.circle color=gray"
        ;;
esac

echo "---"

root_cause=$(echo "$result" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('diagnosis',{}).get('root_cause','Unknown'))" 2>/dev/null)
echo "$root_cause | size=12"

echo "---"
echo "Run Full Diagnosis | bash=$PYTHON param1=-m param2=proxy_doctor.cli param3=check param4=--human terminal=true"
echo "Copy JSON Report | bash=$PYTHON param1=-m param2=proxy_doctor.cli param3=check param4=--json terminal=false | shell=false"
echo "---"
echo "Refresh | refresh=true"
echo "GitHub | href=https://github.com/Jiansen/proxy-doctor"
