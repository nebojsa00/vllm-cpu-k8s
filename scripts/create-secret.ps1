
param(
    [string]$Namespace = "vllm",
    [string]$SecretName = "vllm-secrets",
    [string]$HFToken = ""
)

$ErrorActionPreference = "Stop"

# Проверяем доступность Kubernetes
kubectl get namespace $Namespace | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Kubernetes namespace '$Namespace' not found."
}

$existing = kubectl get secret $SecretName `
    -n $Namespace `
    --ignore-not-found `
    -o name

if ($LASTEXITCODE -ne 0) {
    throw "Failed to check existing Kubernetes Secret."
}

if ($existing) {
    Write-Host "Secret '$SecretName' already exists. Nothing changed."
    exit 0
}

# Генерируем криптографически случайный API-токен
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

try {
    $rng.GetBytes($bytes)
}
finally {
    $rng.Dispose()
}

$apiKey = [BitConverter]::ToString($bytes).
    Replace("-", "").
    ToLowerInvariant()

# Создаем Secret через stdin, не сохраняя токен в файл
$secret = @{
    apiVersion = "v1"
    kind = "Secret"
    metadata = @{
        name = $SecretName
        namespace = $Namespace
    }
    type = "Opaque"
    stringData = @{
        HF_TOKEN = $HFToken
        VLLM_API_KEY = $apiKey
    }
}

$json = $secret | ConvertTo-Json -Depth 6

$json | kubectl apply -f -

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create Kubernetes Secret."
}

Write-Host "Kubernetes Secret created successfully."
Write-Host "API token stored in Kubernetes Secret."
Write-Host "Token value was not printed."
