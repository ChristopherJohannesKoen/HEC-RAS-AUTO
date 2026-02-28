Dim ras
Set ras = CreateObject("RAS66.HECRASController")
Dim prj
prj = "D:\Documents\HEC-RAS-AUTO\Code\HEC-RAS-AUTO\runs\baseline_live_run\ras_project\Meerlustkloof.prj"
On Error Resume Next
ras.Project_Open prj
WScript.Echo "ErrOpen=" & Err.Number & " " & Err.Description
Err.Clear
WScript.Echo "Project_Current=" & ras.Project_Current()
WScript.Echo "CurrentProjectFile=" & ras.CurrentProjectFile()
WScript.Echo "CurrentPlanFile=" & ras.CurrentPlanFile()
Dim count, names, onlyBase
count = 0
onlyBase = True
names = ""
ras.Plan_Names count, names, onlyBase
WScript.Echo "PlanCount=" & count
WScript.Echo "PlanNames=" & names
Dim nmsg, msgs, block, ok
nmsg = 0
msgs = ""
block = True
ok = ras.Compute_CurrentPlan(nmsg, msgs, block)
WScript.Echo "ComputeOK=" & ok
WScript.Echo "nmsg=" & nmsg
WScript.Echo "msgs=" & msgs
ras.QuitRas
