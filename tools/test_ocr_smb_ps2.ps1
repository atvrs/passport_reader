# End-to-end SMB test for passport_reader.
# Compatible with old Windows PowerShell versions.
# Run from 1C server:
#   powershell -ExecutionPolicy Bypass -File .\test_ocr_smb_ps2.ps1

$ErrorActionPreference = "Stop"

$Root = $env:PASSPORT_READER_SMB_ROOT
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = "\\OCR-SERVER\passport_reader"
}
$InDir = Join-Path $Root "in"
$CommandsDir = Join-Path $Root "commands"
$OutDir = Join-Path $Root "out"

$LocalImage = "C:\Users\vrs\test1.jpg"
$RequestId = "SMB_TEST_" + (Get-Date -Format "yyyyMMdd_HHmmss")

function Write-Utf8FileNoBom($Path, $Text) {
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $Encoding)
}

function Get-JsonStringValue($JsonText, $Name) {
    $Pattern = '"' + [Regex]::Escape($Name) + '"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"'
    $Match = [Regex]::Match($JsonText, $Pattern)
    if ($Match.Success) {
        return $Match.Groups[1].Value
    }
    return $null
}

function Require-Directory($Path) {
    if (-not (Test-Path $Path)) {
        throw "Directory not available: $Path"
    }
    Write-Host "OK: $Path"
}

Write-Host "=== SMB ACCESS TEST ==="
Require-Directory $InDir
Require-Directory $CommandsDir
Require-Directory $OutDir

Write-Host ""
Write-Host "=== SMB WRITE / RENAME / DELETE TEST ==="
$ProbeTmp = Join-Path $InDir ("SMB_PROBE_" + $RequestId + ".tmp")
$ProbeFinal = Join-Path $InDir ("SMB_PROBE_" + $RequestId + ".txt")
Write-Utf8FileNoBom $ProbeTmp "probe"
Rename-Item $ProbeTmp $ProbeFinal
Remove-Item $ProbeFinal
Write-Host "OK: write/rename/delete"

Write-Host ""
Write-Host "=== OCR END-TO-END TEST ==="
Write-Host "RequestId: $RequestId"

if (-not (Test-Path $LocalImage)) {
    throw "Local image not found: $LocalImage"
}

$ImageTmpName = $RequestId + ".jpg.tmp"
$ImageName = $RequestId + ".jpg"
$CommandTmpName = $RequestId + ".json.tmp"
$CommandName = $RequestId + ".json"

$ImageTmpPath = Join-Path $InDir $ImageTmpName
$ImagePath = Join-Path $InDir $ImageName
$CommandTmpPath = Join-Path $CommandsDir $CommandTmpName
$CommandPath = Join-Path $CommandsDir $CommandName
$ResultPath = Join-Path $OutDir $CommandName

Remove-Item $ImageTmpPath -ErrorAction SilentlyContinue
Remove-Item $ImagePath -ErrorAction SilentlyContinue
Remove-Item $CommandTmpPath -ErrorAction SilentlyContinue
Remove-Item $CommandPath -ErrorAction SilentlyContinue
Remove-Item $ResultPath -ErrorAction SilentlyContinue

Write-Host "Copy image tmp..."
Copy-Item $LocalImage $ImageTmpPath

Write-Host "Rename image tmp -> jpg..."
Rename-Item $ImageTmpPath $ImageName

$CommandJson = "{" + [Environment]::NewLine +
    "  `"request_id`": `"$RequestId`"," + [Environment]::NewLine +
    "  `"image_file`": `"$ImageName`"" + [Environment]::NewLine +
    "}" + [Environment]::NewLine

Write-Host "Write command tmp..."
Write-Utf8FileNoBom $CommandTmpPath $CommandJson

Write-Host "Rename command tmp -> json..."
Rename-Item $CommandTmpPath $CommandName

Write-Host "Waiting result: $ResultPath"

$Deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $Deadline) {
    if (Test-Path $ResultPath) {
        break
    }
    Start-Sleep -Seconds 1
}

if (-not (Test-Path $ResultPath)) {
    throw "Result file not found: $ResultPath"
}

Write-Host ""
Write-Host "Result file found."
Write-Host ""

$ResultText = [System.IO.File]::ReadAllText($ResultPath, [System.Text.Encoding]::UTF8)

$ValidationStatus = Get-JsonStringValue $ResultText "status"
$LastName = Get-JsonStringValue $ResultText "last_name"
$FirstName = Get-JsonStringValue $ResultText "first_name"
$MiddleName = Get-JsonStringValue $ResultText "middle_name"
$Sex = Get-JsonStringValue $ResultText "sex"
$BirthDate = Get-JsonStringValue $ResultText "birth_date"
$BirthPlace = Get-JsonStringValue $ResultText "birth_place"
$IssueDate = Get-JsonStringValue $ResultText "issue_date"
$DepartmentCode = Get-JsonStringValue $ResultText "department_code"
$IssuedBy = Get-JsonStringValue $ResultText "issued_by"
$DocumentNumber = Get-JsonStringValue $ResultText "document_number"

Write-Host "validation.status: $ValidationStatus"
Write-Host "last_name: $LastName"
Write-Host "first_name: $FirstName"
Write-Host "middle_name: $MiddleName"
Write-Host "sex: $Sex"
Write-Host "birth_date: $BirthDate"
Write-Host "birth_place: $BirthPlace"
Write-Host "issue_date: $IssueDate"
Write-Host "department_code: $DepartmentCode"
Write-Host "issued_by: $IssuedBy"
Write-Host "document_number: $DocumentNumber"
Write-Host ""
Write-Host "Result path: $ResultPath"
Write-Host ""

if ($ValidationStatus -ne "ok") {
    throw "Unexpected validation.status: $ValidationStatus"
}

if ($BirthPlace -ne "ГОР. ТЕСТОВСК") {
    throw "Unexpected birth_place: $BirthPlace"
}

Write-Host "OK: OCR end-to-end test passed"
