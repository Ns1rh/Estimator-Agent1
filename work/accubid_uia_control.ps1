param(
  [ValidateSet('scan','tree','click-name','click-window','type','press','focus')]
  [string]$Action = 'scan',

  [string]$App = 'Accubid',
  [int]$Handle = 0,
  [string]$Name = '',
  [string]$Value = '',
  [string]$Key = 'Enter',
  [int]$X = 0,
  [int]$Y = 0,
  [int]$Depth = 4
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class UiaWin {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@

function Get-TopWindows {
  $windows = New-Object System.Collections.Generic.List[object]
  $cb = [UiaWin+EnumWindowsProc]{
    param([IntPtr]$hWnd, [IntPtr]$lParam)
    if (-not [UiaWin]::IsWindowVisible($hWnd)) { return $true }
    $len = [UiaWin]::GetWindowTextLength($hWnd)
    if ($len -le 0) { return $true }
    $sb = New-Object System.Text.StringBuilder ($len + 1)
    [void][UiaWin]::GetWindowText($hWnd, $sb, $sb.Capacity)
    $windowProcessId = 0
    [void][UiaWin]::GetWindowThreadProcessId($hWnd, [ref]$windowProcessId)
    $proc = ''
    try { $proc = (Get-Process -Id $windowProcessId -ErrorAction Stop).ProcessName } catch {}
    $windows.Add([pscustomobject]@{
      Handle = $hWnd.ToInt64()
      ProcessId = $windowProcessId
      ProcessName = $proc
      Title = $sb.ToString()
    })
    return $true
  }
  [void][UiaWin]::EnumWindows($cb, [IntPtr]::Zero)
  $windows
}

function Get-RootElement {
  if ($Handle -ne 0) {
    return [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Handle)
  }
  $win = Get-TopWindows |
    Where-Object { $_.Title -match $App -or $_.ProcessName -match $App } |
    Select-Object -First 1
  if ($null -eq $win) { throw "No visible window found matching '$App'. Open Accubid first or pass -Handle." }
  return [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([int64]$win.Handle))
}

function Get-ControlTypeName($el) {
  try {
    return $el.Current.ControlType.ProgrammaticName.Replace('ControlType.', '')
  } catch {
    return ''
  }
}

function Walk-Uia {
  param(
    [System.Windows.Automation.AutomationElement]$Element,
    [int]$Level = 0,
    [int]$MaxDepth = 4
  )
  if ($null -eq $Element -or $Level -gt $MaxDepth) { return }
  $indent = '  ' * $Level
  $name = $Element.Current.Name
  $type = Get-ControlTypeName $Element
  $autoId = $Element.Current.AutomationId
  $enabled = $Element.Current.IsEnabled
  [pscustomobject]@{
    Level = $Level
    Type = $type
    Name = $name
    AutomationId = $autoId
    Enabled = $enabled
  }
  if ($Level -eq $MaxDepth) { return }
  $children = $Element.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
  foreach ($child in $children) {
    Walk-Uia -Element $child -Level ($Level + 1) -MaxDepth $MaxDepth
  }
}

function Find-ByName {
  param(
    [System.Windows.Automation.AutomationElement]$Root,
    [string]$Needle
  )
  $all = $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
  for ($i = 0; $i -lt $all.Count; $i++) {
    $el = $all.Item($i)
    if (($el.Current.Name -as [string]) -and $el.Current.Name.ToLowerInvariant().Contains($Needle.ToLowerInvariant())) {
      return $el
    }
  }
  return $null
}

switch ($Action) {
  'scan' {
    Get-TopWindows |
      Where-Object { $_.Title -match 'Accubid|Trimble|LiveCount' -or $_.ProcessName -match 'Accu|LiveCount' } |
      Sort-Object ProcessName,Title |
      Format-Table -AutoSize
  }
  'tree' {
    $root = Get-RootElement
    Walk-Uia -Element $root -MaxDepth $Depth | Format-Table -AutoSize
  }
  'focus' {
    $root = Get-RootElement
    [void][UiaWin]::SetForegroundWindow([IntPtr]$root.Current.NativeWindowHandle)
    Write-Host "Focused: $($root.Current.Name)"
  }
  'click-name' {
    if ([string]::IsNullOrWhiteSpace($Name)) { throw "Pass -Name with visible control text to click." }
    $root = Get-RootElement
    $el = Find-ByName -Root $root -Needle $Name
    if ($null -eq $el) { throw "No UI element found containing name '$Name'." }
    [void][UiaWin]::SetForegroundWindow([IntPtr]$root.Current.NativeWindowHandle)
    $invoke = $null
    if ($el.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke)) {
      $invoke.Invoke()
      Write-Host "Invoked: $($el.Current.Name)"
    } else {
      $rect = $el.Current.BoundingRectangle
      [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point ([int]($rect.X + $rect.Width / 2)), ([int]($rect.Y + $rect.Height / 2))
      [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
      Write-Host "Focused/click fallback: $($el.Current.Name)"
    }
  }
  'click-window' {
    $root = Get-RootElement
    [void][UiaWin]::SetForegroundWindow([IntPtr]$root.Current.NativeWindowHandle)
    Start-Sleep -Milliseconds 200
    $rect = New-Object UiaWin+RECT
    [void][UiaWin]::GetWindowRect([IntPtr]$root.Current.NativeWindowHandle, [ref]$rect)
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point ($rect.Left + $X), ($rect.Top + $Y)
    [UiaWin]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [UiaWin]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Write-Host "Clicked window-relative: $X,$Y"
  }
  'type' {
    if ([string]::IsNullOrWhiteSpace($Value)) { throw "Pass -Value text to type." }
    $root = Get-RootElement
    [void][UiaWin]::SetForegroundWindow([IntPtr]$root.Current.NativeWindowHandle)
    [System.Windows.Forms.SendKeys]::SendWait($Value)
    Write-Host "Typed text into focused Accubid control."
  }
  'press' {
    $root = Get-RootElement
    [void][UiaWin]::SetForegroundWindow([IntPtr]$root.Current.NativeWindowHandle)
    $sendKey = switch ($Key.ToLowerInvariant()) {
      'enter' { '{ENTER}' }
      'tab' { '{TAB}' }
      'escape' { '{ESC}' }
      'esc' { '{ESC}' }
      'down' { '{DOWN}' }
      'up' { '{UP}' }
      'left' { '{LEFT}' }
      'right' { '{RIGHT}' }
      default { $Key }
    }
    [System.Windows.Forms.SendKeys]::SendWait($sendKey)
    Write-Host "Pressed: $Key"
  }
}
