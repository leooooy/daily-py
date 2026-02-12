<#
DailyPy - PowerShell 脚本：从视频中提取一帧
优先使用 FFmpeg（如果可用），否则回退到 Python 端的 moviepy 实现。
Usage:
  pw_extract_frame.ps1 -VideoPath <path> -TimeSec <seconds> [-OutputPath <path>] [-Backend auto|ffmpeg|moviepy]
Notes:
- 需要系统中已安装 FFmpeg，且在 PATH 中可执行 ffmpeg
- 如果选择 backend auto，且 FFmpeg 不可用，将回退到 moviepy；若 moviepy 不可用，则脚本会报错。
#>

param(
  [Parameter(Mandatory=$true)][string]$VideoPath,
  [Parameter(Mandatory=$true)][double]$TimeSec,
  [Parameter()][string]$OutputPath = "",
  [Parameter()][ValidateSet("auto","ffmpeg","moviepy")][string]$Backend = "auto"
)

function Get-FFmpegPath {
  $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($null -ne $cmd) { return $cmd.Source }
  return $null
}

$VideoPath = (Resolve-Path $VideoPath).Path
if (-not (Test-Path $VideoPath)) {
  Write-Error "视频文件不存在: $VideoPath"; exit 1
}

if ($OutputPath -and $OutputPath.Trim().Length -gt 0) {
  $OutputPath = (Resolve-Path $OutputPath).Path
} else {
  $OutputPath = ([IO.Path]::ChangeExtension($VideoPath, ".png"))
}

$OutputDir = Split-Path $OutputPath -Parent
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$ffmpegPath = Get-FFmpegPath
if (($Backend -eq "ffmpeg" -or ($Backend -eq "auto" -and $ffmpegPath)) -and $ffmpegPath) {
  $cmd = & $ffmpegPath -ss $TimeSec -i "$VideoPath" -frames:v 1 -f image2 "$OutputPath" 2>&1
  if ($LASTEXITCODE -ne 0) {
    Write-Error "FFmpeg 提取失败: $cmd"
    exit 1
  }
  Write-Output "FFmpeg 已提取帧：$OutputPath"
  exit 0
}

if ($Backend -eq "moviepy" -or $Backend -eq "auto" -and -not $ffmpegPath) {
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 未安装，无法使用 moviepy 回退：请安装 FFmpeg 或 Python 环境以继续"
    exit 1
  }
  $pythonCmd = @'
from daily_py.image_handler import ImageHandler
ih = ImageHandler(base_path=".")
print(ih.extract_frame(r"{VIDEO}", float({TIME}), output_path=r"{OUTPUT}", backend="auto"))
'@
  $pythonCmd = $pythonCmd.Replace("{VIDEO}", $VideoPath).Replace("{TIME}", [double]$TimeSec).Replace("{OUTPUT}", $OutputPath)
  & python -c $pythonCmd
  if ($LASTEXITCODE -ne 0) {
    Write-Error "MoviePy 提取失败"
    exit 1
  }
  exit 0
}

Write-Error "未找到合适的后端来提取帧，请确保 FFmpeg 已安装且可执行，或使用 moviepy。"
exit 1
