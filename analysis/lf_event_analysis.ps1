param(
    [string]$WorkbookPath = "C:\Users\P_BULUT\Desktop\lf_vs_special_events_2025-01-01_2026-12-31.xlsx",
    [string]$OutputDir = "C:\Users\P_BULUT\Documents\specialevents-schedule\analysis\output"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Variance {
    param(
        [double]$Sum,
        [double]$SumSq,
        [int]$N
    )

    if ($N -le 1) {
        return 0.0
    }

    $variance = ($SumSq - (($Sum * $Sum) / $N)) / ($N - 1)
    return [Math]::Max(0.0, $variance)
}

function Convert-FromExcelDate {
    param($Value)

    if ($Value -is [double] -or $Value -is [int]) {
        return [datetime]::FromOADate([double]$Value)
    }

    return [datetime]::Parse([string]$Value)
}

function Release-ComObject {
    param($ComObject)

    if ($null -ne $ComObject) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ComObject)
    }
}

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$excel = $null
$workbook = $null
$worksheet = $null
$chartWorkbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($WorkbookPath, $null, $true)
    $worksheet = $workbook.Worksheets.Item("joined_airport_day")
    $data = $worksheet.UsedRange.Value2

    $rowCount = $data.GetLength(0)
    $columnCount = $data.GetLength(1)

    $headers = @{}
    for ($column = 1; $column -le $columnCount; $column++) {
        $headers[[string]$data[1, $column]] = $column
    }

    $records = New-Object "System.Collections.Generic.List[object]"
    $airportStats = @{}
    $weekdayNonEvent = @{}

    for ($row = 2; $row -le $rowCount; $row++) {
        $airport = [string]$data[$row, $headers["AIRPORT"]]
        if ([string]::IsNullOrWhiteSpace($airport)) {
            continue
        }

        $lfPct = [double]$data[$row, $headers["LF_PCT"]]
        $eventFlag = [int]$data[$row, $headers["special_event_flag"]]
        $highFlag = [int]$data[$row, $headers["high_impact_flag"]]
        $maxImpact = [double]$data[$row, $headers["max_impact"]]
        $eventNames = [string]$data[$row, $headers["event_names"]]
        $date = Convert-FromExcelDate $data[$row, $headers["flight_date"]]
        $weekday = [int]$date.DayOfWeek

        if (-not $airportStats.ContainsKey($airport)) {
            $airportStats[$airport] = [ordered]@{
                airport = $airport
                totalN = 0
                totalSum = 0.0
                totalSumSq = 0.0
                eventN = 0
                eventSum = 0.0
                eventSumSq = 0.0
                nonN = 0
                nonSum = 0.0
                nonSumSq = 0.0
                highN = 0
                highSum = 0.0
                highSumSq = 0.0
                nonHighN = 0
                nonHighSum = 0.0
                nonHighSumSq = 0.0
                eventNames = New-Object "System.Collections.Generic.HashSet[string]"
                adjustedExcessSum = 0.0
                adjustedExcessN = 0
                highAdjustedExcessSum = 0.0
                highAdjustedExcessN = 0
            }
        }

        $stats = $airportStats[$airport]
        $stats.totalN++
        $stats.totalSum += $lfPct
        $stats.totalSumSq += ($lfPct * $lfPct)

        if ($eventFlag -eq 1) {
            $stats.eventN++
            $stats.eventSum += $lfPct
            $stats.eventSumSq += ($lfPct * $lfPct)
            if (-not [string]::IsNullOrWhiteSpace($eventNames)) {
                [void]$stats.eventNames.Add($eventNames)
            }
        }
        else {
            $stats.nonN++
            $stats.nonSum += $lfPct
            $stats.nonSumSq += ($lfPct * $lfPct)

            $weekdayKey = "$airport|$weekday"
            if (-not $weekdayNonEvent.ContainsKey($weekdayKey)) {
                $weekdayNonEvent[$weekdayKey] = [ordered]@{ n = 0; sum = 0.0 }
            }
            $weekdayNonEvent[$weekdayKey].n++
            $weekdayNonEvent[$weekdayKey].sum += $lfPct
        }

        if ($highFlag -eq 1) {
            $stats.highN++
            $stats.highSum += $lfPct
            $stats.highSumSq += ($lfPct * $lfPct)
        }
        else {
            $stats.nonHighN++
            $stats.nonHighSum += $lfPct
            $stats.nonHighSumSq += ($lfPct * $lfPct)
        }

        $records.Add([pscustomobject]@{
            Airport = $airport
            FlightDate = $date
            Weekday = $weekday
            LFPct = $lfPct
            EventFlag = $eventFlag
            HighFlag = $highFlag
            MaxImpact = $maxImpact
            EventNames = $eventNames
        }) | Out-Null
    }

    foreach ($record in $records) {
        if ($record.EventFlag -ne 1) {
            continue
        }

        $weekdayKey = "$($record.Airport)|$($record.Weekday)"
        if (-not $weekdayNonEvent.ContainsKey($weekdayKey)) {
            continue
        }

        if ($weekdayNonEvent[$weekdayKey].n -lt 3) {
            continue
        }

        $baseline = $weekdayNonEvent[$weekdayKey].sum / $weekdayNonEvent[$weekdayKey].n
        $excess = $record.LFPct - $baseline
        $stats = $airportStats[$record.Airport]
        $stats.adjustedExcessSum += $excess
        $stats.adjustedExcessN++

        if ($record.HighFlag -eq 1) {
            $stats.highAdjustedExcessSum += $excess
            $stats.highAdjustedExcessN++
        }
    }

    $results = foreach ($airport in $airportStats.Keys) {
        $stats = $airportStats[$airport]

        $avgLf = if ($stats.totalN -gt 0) { $stats.totalSum / $stats.totalN } else { $null }
        $avgEventLf = if ($stats.eventN -gt 0) { $stats.eventSum / $stats.eventN } else { $null }
        $avgNonEventLf = if ($stats.nonN -gt 0) { $stats.nonSum / $stats.nonN } else { $null }
        $avgHighLf = if ($stats.highN -gt 0) { $stats.highSum / $stats.highN } else { $null }
        $avgNonHighLf = if ($stats.nonHighN -gt 0) { $stats.nonHighSum / $stats.nonHighN } else { $null }

        $eventUplift = if ($null -ne $avgEventLf -and $null -ne $avgNonEventLf) { $avgEventLf - $avgNonEventLf } else { $null }
        $highImpactUplift = if ($null -ne $avgHighLf -and $null -ne $avgNonHighLf) { $avgHighLf - $avgNonHighLf } else { $null }
        $weekdayAdjustedEventExcess = if ($stats.adjustedExcessN -gt 0) { $stats.adjustedExcessSum / $stats.adjustedExcessN } else { $null }
        $weekdayAdjustedHighImpactExcess = if ($stats.highAdjustedExcessN -gt 0) { $stats.highAdjustedExcessSum / $stats.highAdjustedExcessN } else { $null }

        $tStat = $null
        $pValue = $null
        if ($stats.eventN -ge 2 -and $stats.nonN -ge 2) {
            $varEvent = Get-Variance -Sum $stats.eventSum -SumSq $stats.eventSumSq -N $stats.eventN
            $varNonEvent = Get-Variance -Sum $stats.nonSum -SumSq $stats.nonSumSq -N $stats.nonN
            $standardError = [Math]::Sqrt(($varEvent / $stats.eventN) + ($varNonEvent / $stats.nonN))

            if ($standardError -gt 0) {
                $tStat = ($avgEventLf - $avgNonEventLf) / $standardError
                $dofNumerator = [Math]::Pow(($varEvent / $stats.eventN) + ($varNonEvent / $stats.nonN), 2)
                $dofDenominator = 0.0
                if ($stats.eventN -gt 1) {
                    $dofDenominator += [Math]::Pow($varEvent / $stats.eventN, 2) / ($stats.eventN - 1)
                }
                if ($stats.nonN -gt 1) {
                    $dofDenominator += [Math]::Pow($varNonEvent / $stats.nonN, 2) / ($stats.nonN - 1)
                }

                if ($dofDenominator -gt 0) {
                    $degreesOfFreedom = $dofNumerator / $dofDenominator
                    $pValue = [double]$excel.WorksheetFunction.T_Dist_2T([Math]::Abs($tStat), $degreesOfFreedom)
                }
            }
        }

        [pscustomobject]@{
            AIRPORT = $airport
            n_rows = $stats.totalN
            event_days = $stats.eventN
            high_impact_days = $stats.highN
            avg_lf_pct = [Math]::Round($avgLf, 2)
            avg_event_lf_pct = if ($null -ne $avgEventLf) { [Math]::Round($avgEventLf, 2) } else { $null }
            avg_non_event_lf_pct = if ($null -ne $avgNonEventLf) { [Math]::Round($avgNonEventLf, 2) } else { $null }
            event_uplift_pct_pts = if ($null -ne $eventUplift) { [Math]::Round($eventUplift, 2) } else { $null }
            weekday_adjusted_event_excess = if ($null -ne $weekdayAdjustedEventExcess) { [Math]::Round($weekdayAdjustedEventExcess, 2) } else { $null }
            avg_high_impact_lf_pct = if ($null -ne $avgHighLf) { [Math]::Round($avgHighLf, 2) } else { $null }
            high_impact_uplift_pct_pts = if ($null -ne $highImpactUplift) { [Math]::Round($highImpactUplift, 2) } else { $null }
            weekday_adjusted_high_impact_excess = if ($null -ne $weekdayAdjustedHighImpactExcess) { [Math]::Round($weekdayAdjustedHighImpactExcess, 2) } else { $null }
            t_stat = if ($null -ne $tStat) { [Math]::Round($tStat, 3) } else { $null }
            p_value = if ($null -ne $pValue) { [Math]::Round($pValue, 6) } else { $null }
            event_names = (($stats.eventNames | Select-Object -First 3) -join " ; ")
        }
    }

    $resultsPath = Join-Path $OutputDir "airport_event_effects.csv"
    $results | Sort-Object AIRPORT | Export-Csv -Path $resultsPath -NoTypeInformation -Encoding UTF8

    $proven = $results |
        Where-Object {
            $_.event_days -ge 5 -and
            $_.high_impact_days -ge 2 -and
            $_.event_uplift_pct_pts -ge 5 -and
            $_.weekday_adjusted_event_excess -ge 3 -and
            $_.p_value -ne $null -and
            $_.p_value -le 0.05
        } |
        Sort-Object @{ Expression = "weekday_adjusted_event_excess"; Descending = $true }, @{ Expression = "event_uplift_pct_pts"; Descending = $true }

    $topAirports = @($proven | Select-Object -First 6 -ExpandProperty AIRPORT)

    $timelineRows = foreach ($airport in $topAirports) {
        $airportRecords = $records |
            Where-Object { $_.Airport -eq $airport -and $_.EventFlag -eq 1 } |
            Sort-Object @{ Expression = "MaxImpact"; Descending = $true }, @{ Expression = "FlightDate"; Descending = $false }

        if ($airportRecords.Count -eq 0) {
            continue
        }

        $peakRecord = $airportRecords | Select-Object -First 1
        $startDate = $peakRecord.FlightDate.AddDays(-14)
        $endDate = $peakRecord.FlightDate.AddDays(14)

        foreach ($record in ($records | Where-Object { $_.Airport -eq $airport -and $_.FlightDate -ge $startDate -and $_.FlightDate -le $endDate } | Sort-Object FlightDate)) {
            [pscustomobject]@{
                AIRPORT = $airport
                flight_date = $record.FlightDate.ToString("yyyy-MM-dd")
                LF_PCT = [Math]::Round($record.LFPct, 2)
                max_impact = [Math]::Round($record.MaxImpact, 2)
                special_event_flag = $record.EventFlag
                event_names = $record.EventNames
            }
        }
    }

    $timelinePath = Join-Path $OutputDir "top_airport_timelines.csv"
    $timelineRows | Export-Csv -Path $timelinePath -NoTypeInformation -Encoding UTF8

    $chartWorkbook = $excel.Workbooks.Add()

    $summarySheet = $chartWorkbook.Worksheets.Item(1)
    $summarySheet.Name = "summary"
    $summaryHeaders = @(
        "AIRPORT",
        "event_days",
        "high_impact_days",
        "avg_event_lf_pct",
        "avg_non_event_lf_pct",
        "event_uplift_pct_pts",
        "weekday_adjusted_event_excess",
        "p_value",
        "event_names"
    )

    for ($index = 0; $index -lt $summaryHeaders.Count; $index++) {
        $summarySheet.Cells.Item(1, $index + 1).Value2 = $summaryHeaders[$index]
    }

    $summaryRow = 2
    foreach ($item in $proven | Select-Object -First 10) {
        $summarySheet.Cells.Item($summaryRow, 1).Value2 = $item.AIRPORT
        $summarySheet.Cells.Item($summaryRow, 2).Value2 = $item.event_days
        $summarySheet.Cells.Item($summaryRow, 3).Value2 = $item.high_impact_days
        $summarySheet.Cells.Item($summaryRow, 4).Value2 = $item.avg_event_lf_pct
        $summarySheet.Cells.Item($summaryRow, 5).Value2 = $item.avg_non_event_lf_pct
        $summarySheet.Cells.Item($summaryRow, 6).Value2 = $item.event_uplift_pct_pts
        $summarySheet.Cells.Item($summaryRow, 7).Value2 = $item.weekday_adjusted_event_excess
        $summarySheet.Cells.Item($summaryRow, 8).Value2 = $item.p_value
        $summarySheet.Cells.Item($summaryRow, 9).Value2 = $item.event_names
        $summaryRow++
    }

    $sheetIndex = 2
    foreach ($airport in $topAirports) {
        $airportRows = @($timelineRows | Where-Object { $_.AIRPORT -eq $airport } | Sort-Object flight_date)
        if ($airportRows.Count -eq 0) {
            continue
        }

        if ($sheetIndex -le $chartWorkbook.Worksheets.Count) {
            $chartSheet = $chartWorkbook.Worksheets.Item($sheetIndex)
        }
        else {
            $chartSheet = $chartWorkbook.Worksheets.Add()
        }

        $chartSheet.Name = $airport
        $chartSheet.Cells.Item(1, 1).Value2 = "flight_date"
        $chartSheet.Cells.Item(1, 2).Value2 = "LF_PCT"
        $chartSheet.Cells.Item(1, 3).Value2 = "max_impact"
        $chartSheet.Cells.Item(1, 4).Value2 = "event_flag"
        $chartSheet.Cells.Item(1, 5).Value2 = "event_names"

        $rowIndex = 2
        foreach ($item in $airportRows) {
            $chartSheet.Cells.Item($rowIndex, 1).Value2 = $item.flight_date
            $chartSheet.Cells.Item($rowIndex, 2).Value2 = $item.LF_PCT
            $chartSheet.Cells.Item($rowIndex, 3).Value2 = $item.max_impact
            $chartSheet.Cells.Item($rowIndex, 4).Value2 = $item.special_event_flag
            $chartSheet.Cells.Item($rowIndex, 5).Value2 = $item.event_names
            $rowIndex++
        }

        $chartRange = $chartSheet.Range("A1:C$($airportRows.Count + 1)")
        $chartObject = $chartSheet.ChartObjects().Add(40, 20, 900, 360)
        $chart = $chartObject.Chart
        $chart.ChartType = 4
        $chart.SetSourceData($chartRange)
        $chart.HasTitle = $true
        $chart.ChartTitle.Text = "$airport LF vs Event Impact"
        $chart.SeriesCollection(1).Name = "LF %"
        $chart.SeriesCollection(2).Name = "Max impact"
        $chart.Axes(1).CategoryType = 2
        $chart.Axes(2).HasTitle = $true
        $chart.Axes(2).AxisTitle.Text = "LF % / Impact"

        $chart.Export((Join-Path $OutputDir ("chart_" + $airport + ".png"))) | Out-Null
        $sheetIndex++
    }

    $reportPath = Join-Path $OutputDir "lf_event_effect_report.txt"
    $reportLines = @()
    $reportLines += "Workbook: $WorkbookPath"
    $reportLines += "Sheet: joined_airport_day"
    $reportLines += "Note: the sheet is airport-day grain, so AIRPORT is treated as the route endpoint rather than a directional full route code."
    $reportLines += "Proof criteria: event_days >= 5, high_impact_days >= 2, event uplift >= 5 LF pts, weekday-adjusted excess >= 3 LF pts, Welch p-value <= 0.05"
    $reportLines += ""
    $reportLines += "Top airports with provable positive event effect:"

    foreach ($item in $proven | Select-Object -First 10) {
        $reportLines += (
            "{0}: event days={1}, high-impact days={2}, avg LF event={3}, avg LF non-event={4}, uplift={5} pts, weekday-adjusted excess={6} pts, p={7}, events={8}" -f
            $item.AIRPORT, $item.event_days, $item.high_impact_days, $item.avg_event_lf_pct, $item.avg_non_event_lf_pct, $item.event_uplift_pct_pts, $item.weekday_adjusted_event_excess, $item.p_value, $item.event_names
        )
    }

    Set-Content -Path $reportPath -Value $reportLines -Encoding UTF8

    $chartWorkbookPath = Join-Path $OutputDir "lf_event_charts.xlsx"
    $chartWorkbook.SaveAs($chartWorkbookPath)

    Write-Output "OUTPUT_DIR=$OutputDir"
    Write-Output "RESULTS_CSV=$resultsPath"
    Write-Output "TIMELINE_CSV=$timelinePath"
    Write-Output "REPORT_TXT=$reportPath"
    Write-Output "CHART_WORKBOOK=$chartWorkbookPath"
    Write-Output "PROVEN_COUNT=$($proven.Count)"
    $proven | Select-Object -First 10 | Format-Table -AutoSize
}
finally {
    if ($chartWorkbook -ne $null) {
        $chartWorkbook.Close($true) | Out-Null
    }
    if ($workbook -ne $null) {
        $workbook.Close($false) | Out-Null
    }
    if ($excel -ne $null) {
        $excel.Quit()
    }

    Release-ComObject $worksheet
    Release-ComObject $workbook
    Release-ComObject $chartWorkbook
    Release-ComObject $excel
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
