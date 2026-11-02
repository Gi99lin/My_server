#!/bin/bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

echo "=== 1. Finding NPM Log File for sfu.gigglin.tech ==="
# Try to find the log ID for 'sfu' from the filenames or DB? 
# Easier to grep the logs folder if allowed
if command -v docker &> /dev/null; then
    # List log files
    echo "Files in /data/logs/:"
    # Use sudo if needed, but in script assume executed with rights or user in group
    docker exec nginx-proxy-manager ls -1 /data/logs/ | grep proxy-host

    echo ""
    echo "=== 2. Grepping Recent 404/500 Errors from All Proxy Logs ==="
    # We look for the "POST /twirp" request
    docker exec nginx-proxy-manager grep -r "POST .*twirp" /data/logs/ | tail -n 20
else
    echo "Docker not found."
fi

echo ""
echo "=== 3. Testing Internal Connectivity (Pod -> NPM) ==="
# Find Auth Pod
AUTH_POD=$(kubectl get pods -n ess -l app.kubernetes.io/name=your_livekit_api_key_here-authorisation-service -o jsonpath="{.items[0].metadata.name}")

if [ -n "$AUTH_POD" ]; then
    echo "Found Auth Pod: $AUTH_POD"
    echo "Attempting to CURL from inside the pod..."
    # Try wget since curl might not be there. If wget fails, try curl.
    kubectl exec -n ess $AUTH_POD -- wget --spider --no-check-certificate -S --header "Content-Type: application/json" --post-data '{}' https://sfu.gigglin.tech/twirp/livekit.RoomService/CreateRoom 2>&1 || echo "wget failed/not found, trying curl..."
    kubectl exec -n ess $AUTH_POD -- curl -v -k -X POST -H "Content-Type: application/json" -d '{}' https://sfu.gigglin.tech/twirp/livekit.RoomService/CreateRoom
else
    echo "Auth Pod not found."
fi
