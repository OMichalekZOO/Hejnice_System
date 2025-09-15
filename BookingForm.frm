VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} BookingForm 
   Caption         =   "Rezervace"
   ClientHeight    =   6300
   ClientLeft      =   120
   ClientTop       =   468
   ClientWidth     =   13872
   OleObjectBlob   =   "BookingForm.frx":0000
   StartUpPosition =   1  'CenterOwner
End
Attribute VB_Name = "BookingForm"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
' ===========================
' BookingForm – COMPLETE CODE (bez kalendáøe)
' ===========================

' ==== HELPERS: safe access to per-room controls (support mixed names) ====
Private Function ArrivalTB(ByVal idx As Long) As MSForms.textbox
    On Error Resume Next
    Set ArrivalTB = Me.Controls("DateArr" & idx)
    If ArrivalTB Is Nothing Then Set ArrivalTB = Me.Controls("DateArrTB" & idx)
    If ArrivalTB Is Nothing Then Set ArrivalTB = Me.Controls("DateArrivalTB" & idx)
    On Error GoTo 0
End Function

Private Function DepartureTB(ByVal idx As Long) As MSForms.textbox
    On Error Resume Next
    Set DepartureTB = Me.Controls("DateDep" & idx)
    If DepartureTB Is Nothing Then Set DepartureTB = Me.Controls("DateDepartureTB" & idx)
    On Error GoTo 0
End Function

Private Function NightsTB(ByVal idx As Long) As MSForms.textbox
    On Error Resume Next
    Set NightsTB = Me.Controls("NumNights" & idx)
    If NightsTB Is Nothing Then Set NightsTB = Me.Controls("NumNightsTB" & idx)
    On Error GoTo 0
End Function

' ==== CORE: per-room nights recompute ====
Private Sub RecalcRoomNights(ByVal idx As Long)
    Dim a As String, d As String
    a = ArrivalTB(idx).Value
    d = DepartureTB(idx).Value

    If Not IsValidDateFormat(a) Or Not IsValidDateFormat(d) Then
        NightsTB(idx).Value = ""
        Exit Sub
    End If

    Dim da As Date, dd As Date, n As Long
    da = CDate(a): dd = CDate(d)
    n = DateDiff("d", da, dd)
    If n < 0 Then
        MsgBox "Odjezd nemùže být døíve než pøíjezd (pokoj " & idx & ").", vbExclamation
        NightsTB(idx).Value = ""
        Exit Sub
    End If

    NightsTB(idx).Value = n
End Sub

' ==== UI EVENTS: per-room date Exit handlers ====
' Pøíjezdy – oèekává DateArr1..6 (pokud máš jinak, helpery to stejnì obslouží)
Private Sub DateArr1_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 1: Call CalculateRoomPrice(1): UpdateTotalPrice
End Sub
Private Sub DateArr2_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 2: Call CalculateRoomPrice(2): UpdateTotalPrice
End Sub
Private Sub DateArr3_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 3: Call CalculateRoomPrice(3): UpdateTotalPrice
End Sub
Private Sub DateArr4_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 4: Call CalculateRoomPrice(4): UpdateTotalPrice
End Sub
Private Sub DateArr5_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 5: Call CalculateRoomPrice(5): UpdateTotalPrice
End Sub
Private Sub DateArr6_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 6: Call CalculateRoomPrice(6): UpdateTotalPrice
End Sub

' Odjezdy – oèekává DateDepartureTB1..6 (nebo DateDep1..6, pokud máš; helpery pomùžou)
Private Sub DateDepartureTB1_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 1: Call CalculateRoomPrice(1): UpdateTotalPrice
End Sub
Private Sub DateDepartureTB2_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 2: Call CalculateRoomPrice(2): UpdateTotalPrice
End Sub
Private Sub DateDepartureTB3_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 3: Call CalculateRoomPrice(3): UpdateTotalPrice
End Sub
Private Sub DateDepartureTB4_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 4: Call CalculateRoomPrice(4): UpdateTotalPrice
End Sub
Private Sub DateDepartureTB5_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 5: Call CalculateRoomPrice(5): UpdateTotalPrice
End Sub
Private Sub DateDepartureTB6_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Me.PerRoomDatesCB.Value Then RecalcRoomNights 6: Call CalculateRoomPrice(6): UpdateTotalPrice
End Sub

' ==== CHECKBOX: toggle per-room dates mode ====
Private Sub PerRoomDatesCB_Click()
    Dim i As Long
    If Me.PerRoomDatesCB.Value = True Then
        ' každý pokoj má vlastní A/D
        For i = 1 To 6
            If Not ArrivalTB(i) Is Nothing Then ArrivalTB(i).Enabled = True
            If Not DepartureTB(i) Is Nothing Then DepartureTB(i).Enabled = True
            RecalcRoomNights i
            Call CalculateRoomPrice(i)
        Next i
    Else
        ' spoleèné A/D
        For i = 1 To 6
            If Not ArrivalTB(i) Is Nothing Then
                ArrivalTB(i).Enabled = False
                ArrivalTB(i).Value = Me.DateArrivalTB.Value
            End If
            If Not DepartureTB(i) Is Nothing Then
                DepartureTB(i).Enabled = False
                DepartureTB(i).Value = Me.DateDepartureTB.Value
            End If
            If Not NightsTB(i) Is Nothing Then NightsTB(i).Value = Me.NumNightsTB.Value
            Call CalculateRoomPrice(i)
        Next i
    End If
    UpdateTotalPrice
End Sub

' ==== USERFORM INIT ====
Private Sub UserForm_Initialize()
    ' Default globální A/D
    Me.DateArrivalTB.Value = Format(Date, "dd.mm.yyyy")
    Me.DateDepartureTB.Value = Format(Date, "dd.mm.yyyy")

    ' Naplnìní typù pokojù
    FillRoomTypes Me.RoomTypeTB1
    FillRoomTypes Me.RoomTypeTB2
    FillRoomTypes Me.RoomTypeTB3
    FillRoomTypes Me.RoomTypeTB4
    FillRoomTypes Me.RoomTypeTB5
    FillRoomTypes Me.RoomTypeTB6

    ' INIT per-room A/D/N: pøevzít globály a vypnout editaci
    Dim i As Long
    For i = 1 To 6
        If Not ArrivalTB(i) Is Nothing Then
            ArrivalTB(i).Value = Me.DateArrivalTB.Value
            ArrivalTB(i).Enabled = False
        End If
        If Not DepartureTB(i) Is Nothing Then
            DepartureTB(i).Value = Me.DateDepartureTB.Value
            DepartureTB(i).Enabled = False
        End If
        If Not NightsTB(i) Is Nothing Then
            NightsTB(i).Value = Me.NumNightsTB.Value
            NightsTB(i).Enabled = False
        End If
    Next i
    Me.PerRoomDatesCB.Value = False
End Sub

' ==== GLOBAL DATE EXITS – globální pøepoèty a synchronizace ====
Private Sub DateArrivalTB_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Not IsValidDateFormat(Me.DateArrivalTB.Value) Then
        MsgBox "Invalid Arrival Date format. Please use dd.mm.yyyy", vbExclamation
        Me.DateArrivalTB.Value = ""
    End If

    Dim DateArrival As Date, DateDeparture As Date, numNights As Long, i As Long
    DateArrival = Me.DateArrivalTB.Value
    DateDeparture = Me.DateDepartureTB.Value
    numNights = DateDiff("d", DateArrival, DateDeparture)

    Me.NumNightsTB.Value = numNights

    If Me.PerRoomDatesCB.Value = False Then
        Dim j As Long
        For j = 1 To 6
            If Not ArrivalTB(j) Is Nothing Then ArrivalTB(j).Value = Me.DateArrivalTB.Value
            If Not DepartureTB(j) Is Nothing Then DepartureTB(j).Value = Me.DateDepartureTB.Value
            If Not NightsTB(j) Is Nothing Then NightsTB(j).Value = numNights
            Call CalculateRoomPrice(j)
        Next j
        UpdateTotalPrice
    End If

    For i = 1 To 6
        Call CalculateRoomPrice(i)
    Next i
End Sub

Private Sub DateDepartureTB_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    If Not IsValidDateFormat(Me.DateDepartureTB.Value) Then
        MsgBox "Invalid Departure Date format. Please use dd.mm.yyyy", vbExclamation
        Me.DateDepartureTB.Value = ""
    End If

    Dim DateArrival As Date, DateDeparture As Date, numNights As Long, i As Long
    DateArrival = Me.DateArrivalTB.Value
    DateDeparture = Me.DateDepartureTB.Value
    numNights = DateDiff("d", DateArrival, DateDeparture)

    Me.NumNightsTB.Value = numNights

    If Me.PerRoomDatesCB.Value = False Then
        Dim j As Long
        For j = 1 To 6
            If Not ArrivalTB(j) Is Nothing Then ArrivalTB(j).Value = Me.DateArrivalTB.Value
            If Not DepartureTB(j) Is Nothing Then DepartureTB(j).Value = Me.DateDepartureTB.Value
            If Not NightsTB(j) Is Nothing Then NightsTB(j).Value = numNights
            Call CalculateRoomPrice(j)
        Next j
        UpdateTotalPrice
    End If

    For i = 1 To 6
        Call CalculateRoomPrice(i)
    Next i
End Sub

' ==== VALIDATION ====
Private Function IsValidDateFormat(ByVal dateString As String) As Boolean
    Dim dt As Date
    dateString = Trim$(dateString)
    If dateString = "" Then IsValidDateFormat = False: Exit Function

    On Error Resume Next
    dt = CDate(dateString)
    If Err.Number <> 0 Then Err.Clear: On Error GoTo 0: IsValidDateFormat = False: Exit Function
    On Error GoTo 0

    IsValidDateFormat = (Format$(dt, "dd.mm.yyyy") = dateString)
End Function

' ==== CREATE ====
Private Sub CreateBTN_Click()
    Dim ws As Worksheet, tbl As ListObject, newRow As ListRow
    Dim Name As String, UniqueID As String
    Dim DateArrival As Date, DateDeparture As Date
    Dim NumRooms As Long, rowIndex As Long

    Set ws = ThisWorkbook.Sheets("Rezervace")
    Set tbl = ws.ListObjects("Assignments")

    If IsEmpty(Me.NameTB) Then
        MsgBox "Vyplòte jméno a pøíjmení!": Exit Sub
    ElseIf IsEmpty(Me.NumNightsTB) Then
        MsgBox "Nelze rezervovat na 0 nocí!": Exit Sub
    ElseIf IsEmpty(Me.NumRoomsTB) Then
        MsgBox "Nebyl vybrán typ pokoje!": Exit Sub
    End If

    Name = Me.NameTB.Value
    UniqueID = Me.IdentTB.Value
    DateArrival = Me.DateArrivalTB.Value
    DateDeparture = Me.DateDepartureTB.Value
    NumRooms = CLng(Me.NumRoomsTB.Value)

    For rowIndex = 1 To NumRooms
        Set newRow = tbl.ListRows.Add(1)
        With newRow
            .Range(1).Value = UniqueID
            .Range(2).Value = Name

            If Me.PerRoomDatesCB.Value = True Then
                .Range(3).Value = ArrivalTB(rowIndex).Value
                .Range(4).Value = DepartureTB(rowIndex).Value
                .Range(5).Value = NightsTB(rowIndex).Value
            Else
                .Range(3).Value = Me.DateArrivalTB.Value
                .Range(4).Value = Me.DateDepartureTB.Value
                .Range(5).Value = Me.NumNightsTB.Value
            End If

            .Range(6).Value = Me.Controls("RoomTypeTB" & rowIndex).Value
            .Range(7).Value = Me.Controls("NumEmployeeTB" & rowIndex).Value
            .Range(8).Value = Me.Controls("NumGuestTB" & rowIndex).Value
            .Range(9).Value = Me.Controls("PriceTB" & rowIndex).Value
        End With
    Next rowIndex

    Unload Me
End Sub

Private Sub CancelBTN_Click()
    Unload Me
End Sub

' ==== ROOMS CHANGES ====
Private Sub RoomTypeTB1_Change(): DisplaySelectedRooms: End Sub
Private Sub RoomTypeTB2_Change(): DisplaySelectedRooms: End Sub
Private Sub RoomTypeTB3_Change(): DisplaySelectedRooms: End Sub
Private Sub RoomTypeTB4_Change(): DisplaySelectedRooms: End Sub
Private Sub RoomTypeTB5_Change(): DisplaySelectedRooms: End Sub
Private Sub RoomTypeTB6_Change(): DisplaySelectedRooms: End Sub

Private Sub NumGuestTB1_Change(): Call CalculateRoomPrice(1): End Sub
Private Sub NumGuestTB2_Change(): Call CalculateRoomPrice(2): End Sub
Private Sub NumGuestTB3_Change(): Call CalculateRoomPrice(3): End Sub
Private Sub NumGuestTB4_Change(): Call CalculateRoomPrice(4): End Sub
Private Sub NumGuestTB5_Change(): Call CalculateRoomPrice(5): End Sub
Private Sub NumGuestTB6_Change(): Call CalculateRoomPrice(6): End Sub

Private Sub NumEmployeeTB1_Change(): Call CalculateRoomPrice(1): End Sub
Private Sub NumEmployeeTB2_Change(): Call CalculateRoomPrice(2): End Sub
Private Sub NumEmployeeTB3_Change(): Call CalculateRoomPrice(3): End Sub
Private Sub NumEmployeeTB4_Change(): Call CalculateRoomPrice(4): End Sub
Private Sub NumEmployeeTB5_Change(): Call CalculateRoomPrice(5): End Sub
Private Sub NumEmployeeTB6_Change(): Call CalculateRoomPrice(6): End Sub

Private Sub PriceTB1_Change(): UpdateTotalPrice: End Sub
Private Sub PriceTB2_Change(): UpdateTotalPrice: End Sub
Private Sub PriceTB3_Change(): UpdateTotalPrice: End Sub
Private Sub PriceTB4_Change(): UpdateTotalPrice: End Sub
Private Sub PriceTB5_Change(): UpdateTotalPrice: End Sub
Private Sub PriceTB6_Change(): UpdateTotalPrice: End Sub

' ==== UTILS ====
Private Sub DisplaySelectedRooms()
    Dim numSelectedRooms As Long, i As Long
    For i = 1 To 6
        If Me.Controls("RoomTypeTB" & i).Value <> "" Then numSelectedRooms = numSelectedRooms + 1
    Next i
    Me.NumRoomsTB.Value = numSelectedRooms
End Sub

Private Sub UpdateTotalPrice()
    Dim totalRoomPrice As Double, i As Long
    For i = 1 To 6
        If IsNumeric(Me.Controls("PriceTB" & i).Value) And Me.Controls("PriceTB" & i).Value <> "" Then
            totalRoomPrice = totalRoomPrice + CDbl(Me.Controls("PriceTB" & i).Value)
        End If
    Next i
    Me.PriceTotalTB.Value = totalRoomPrice
End Sub

Private Function CalculateRoomPrice(ByVal num As Long) As Double
    Dim roomType As String
    Dim numEmployee As Double, numGuest As Double, numNights As Double
    Dim pricePerEmployee As Double, pricePerGuest As Double, price As Double

    Dim ws As Worksheet: Set ws = ThisWorkbook.Sheets("Nastavení")
    Dim configTable As ListObject: Set configTable = ws.ListObjects("Config")

    roomType = Me.Controls("RoomTypeTB" & num).Value
    numEmployee = val(Me.Controls("NumEmployeeTB" & num).Value)
    numGuest = val(Me.Controls("NumGuestTB" & num).Value)

    If Me.PerRoomDatesCB.Value = True Then
        numNights = val(NightsTB(num).Value)
    Else
        numNights = val(Me.NumNightsTB.Value)
    End If

    If roomType = "" Then Exit Function

    Dim rowIndex As Variant
    rowIndex = Application.Match(roomType, configTable.ListColumns("POKOJ").DataBodyRange, 0)
    If Not IsNumeric(rowIndex) Then
        MsgBox "Pokoj neexistuje. Pokud potøebujete pøidat nový pokoj, pøidejte ho v listu Nastavení.", vbExclamation
        Exit Function
    End If

    pricePerEmployee = configTable.ListColumns("CENA Z").DataBodyRange(rowIndex).Value
    pricePerGuest = configTable.ListColumns("CENA N").DataBodyRange(rowIndex).Value

    price = ((pricePerEmployee * numEmployee) + (pricePerGuest * numGuest)) * numNights
    Me.Controls("PriceTB" & num).Value = price
    CalculateRoomPrice = price
End Function

Private Function IsEmpty(textbox As MSForms.textbox) As Boolean
    IsEmpty = (Trim$(textbox.Value) = "")
End Function

Private Sub FillRoomTypes(ByVal comboBox As MSForms.comboBox)
    Dim ws As Worksheet: Set ws = ThisWorkbook.Sheets("Nastavení")
    Dim configTable As ListObject: Set configTable = ws.ListObjects("Config")
    Dim roomTypeCell As Range, roomType As Variant

    Set roomTypeCell = configTable.ListColumns("POKOJ").DataBodyRange
    comboBox.Clear
    For Each roomType In roomTypeCell
        comboBox.AddItem roomType.Value
    Next roomType
End Sub

