$prj = "D:\Documents\HEC-RAS-AUTO\Code\HEC-RAS-AUTO\runs\baseline_live_run\ras_project\Meerlustkloof.prj"
$ras = New-Object -ComObject RAS66.HECRASController
$ras.Project_Open($prj)
Write-Output ("Project_Current=" + $ras.Project_Current())
Write-Output ("CurrentProjectFile=" + $ras.CurrentProjectFile())
Write-Output ("CurrentPlanFile=" + $ras.CurrentPlanFile())
$pc=0; $pn=""; $only=$true
$ras.Plan_Names([ref]$pc, [ref]$pn, [ref]$only)
Write-Output ("PlanCount=" + $pc)
Write-Output ("PlanNames=" + $pn)
$nmsg=0; $msgs=@(); $block=$true
$ok = $ras.Compute_CurrentPlan([ref]$nmsg, [ref]$msgs, [ref]$block)
Write-Output ("ComputeOK=" + $ok)
Write-Output ("nmsg=" + $nmsg)
Write-Output ("msgs=" + ($msgs -join ';'))
$ras.QuitRas() | Out-Null
