VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} EditForm 
   Caption         =   "Upravit Rezervaci"
   ClientHeight    =   6360
   ClientLeft      =   120
   ClientTop       =   468
   ClientWidth     =   9768
   OleObjectBlob   =   "EditForm.frx":0000
   StartUpPosition =   1  'CenterOwner
End
Attribute VB_Name = "EditForm"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Private Sub CancelBTN_Click()
    Unload Me
End Sub

Private Sub UserForm_Initialize()
    Dim v, e
    ' Get the values from the "ID" column in the "Assignments" table
    With Sheets("Rezervace").ListObjects("Assignments").ListColumns("ID").DataBodyRange
        v = .Value
    End With
    
    ' Room section 1
    FillRoomTypes Me.RoomTypeTB1
    ' Room section 2
    FillRoomTypes Me.RoomTypeTB2
    ' Room section 3
    FillRoomTypes Me.RoomTypeTB3
    ' Room section 4
    FillRoomTypes Me.RoomTypeTB4
    ' Room section 5
    FillRoomTypes Me.RoomTypeTB5
    ' Room section 6
    FillRoomTypes Me.RoomTypeTB6

    ' Create a dictionary to store unique values from the "ID" column
    With CreateObject("Scripting.Dictionary")
        .CompareMode = 1 ' Set the dictionary to be case-insensitive
        ' Iterate through the values in the "ID" column and add unique values to the dictionary
        For Each e In v
            If Not .Exists(e) Then .Add e, Nothing
        Next
        ' If there are any unique values in the dictionary, populate them into ComboBox19
        If .Count Then Me.BookingIDCB.List = Application.Transpose(.Keys)
    End With
End Sub

Private Sub BookingIDCB_Change()
    Dim selectedID As String
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim row As ListRow
    Dim i As Integer
    Dim roomCount As Integer
    
    ' Get the selected ID from the ComboBox
    selectedID = BookingIDCB.Value
    
    ' Set the worksheet and table
    Set ws = Worksheets("Rezervace")
    Set tbl = ws.ListObjects("Assignments")
    
    ResetTextBoxes
    
    ' Count the number of rows with the selected ID
    For Each row In tbl.ListRows
        If row.Range(1, 1).Value = selectedID Then
            roomCount = roomCount + 1
        End If
    Next row
    
    ' Search for the row(s) with the matching ID and update TextBoxes
    i = 1 ' Counter for TextBox iteration
    For Each row In tbl.ListRows
        If row.Range(1, 1).Value = selectedID Then
            ' Update general information (for the first room)
            If i = 1 Then
                Me.NameTB.Value = row.Range(1, 2).Value ' JMÉNO A PØÍJMENÍ
                Me.DateArrivalTB.Value = Format(row.Range(1, 3).Value, "dd.mm.yyyy") ' DATUM PØÍJEZDU
                Me.DateDepartureTB.Value = Format(row.Range(1, 4).Value, "dd.mm.yyyy") ' DATUM ODJEZDU
                Me.NumNightsTB.Value = row.Range(1, 5).Value ' POÈET NOCÍ
                Me.NumRoomsTB.Value = roomCount
            End If
            
            ' Update TextBoxes for each room
            Me.Controls("RoomTypeTB" & i).Value = row.Range(1, 6).Value ' POKOJ
            Me.Controls("NumEmployeeTB" & i).Value = row.Range(1, 7).Value ' Z
            Me.Controls("NumGuestTB" & i).Value = row.Range(1, 8).Value ' N
            Me.Controls("PriceTB" & i).Value = row.Range(1, 9).Value ' CENA
            
            i = i + 1 ' Increment counter for the next iteration
        End If
    Next row
End Sub

Private Sub RoomTypeTB1_Change()
    DisplaySelectedRooms
End Sub

Private Sub RoomTypeTB2_Change()
    DisplaySelectedRooms
End Sub

Private Sub RoomTypeTB3_Change()
    DisplaySelectedRooms
End Sub

Private Sub RoomTypeTB4_Change()
    DisplaySelectedRooms
End Sub

Private Sub RoomTypeTB5_Change()
    DisplaySelectedRooms
End Sub

Private Sub RoomTypeTB6_Change()
    DisplaySelectedRooms
End Sub

Private Sub NumGuestTB1_Change()
    CalculateRoomPrice (1)
End Sub

Private Sub NumGuestTB2_Change()
    CalculateRoomPrice (2)
End Sub

Private Sub NumGuestTB3_Change()
    CalculateRoomPrice (3)
End Sub

Private Sub NumGuestTB4_Change()
    CalculateRoomPrice (4)
End Sub

Private Sub NumGuestTB5_Change()
    CalculateRoomPrice (5)
End Sub

Private Sub NumGuestTB6_Change()
    CalculateRoomPrice (6)
End Sub

Private Sub NumEmployeeTB1_Change()
    CalculateRoomPrice (1)
End Sub

Private Sub NumEmployeeTB2_Change()
    CalculateRoomPrice (2)
End Sub

Private Sub NumEmployeeTB3_Change()
    CalculateRoomPrice (3)
End Sub

Private Sub NumEmployeeTB4_Change()
    CalculateRoomPrice (4)
End Sub

Private Sub NumEmployeeTB5_Change()
    CalculateRoomPrice (5)
End Sub

Private Sub NumEmployeeTB6_Change()
    CalculateRoomPrice (6)
End Sub

Private Sub PriceTB1_Change()
    UpdateTotalPrice
End Sub

Private Sub PriceTB2_Change()
    UpdateTotalPrice
End Sub

Private Sub PriceTB3_Change()
    UpdateTotalPrice
End Sub

Private Sub PriceTB4_Change()
    UpdateTotalPrice
End Sub

Private Sub PriceTB5_Change()
    UpdateTotalPrice
End Sub

Private Sub PriceTB6_Change()
    UpdateTotalPrice
End Sub

Private Sub UpdateBTN_Click()
    ' Get the selected ID from the ComboBox
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim newColumn As ListColumn
    Dim colIndex As Integer
    Dim rowIndex As Integer
    Dim selectedID As String
    Dim Name As String
    Dim DateArrival As Date
    Dim DateDeparture As Date
    Dim NumRooms As Integer
    
    selectedID = BookingIDCB.Value

    Set ws = Worksheets("Rezervace")
    Set tbl = ws.ListObjects("Assignments")
    
    ' Create new rows based on the UserForm data
    If IsEmpty(Me.NameTB) Then
        MsgBox "Vyplòte jméno a pøíjmení!"
    ElseIf IsEmpty(Me.NumNightsTB) Then
        MsgBox "Nelze rezervovat na 0 nocí!"
    ElseIf IsEmpty(Me.NumRoomsTB) Then
        MsgBox "Nebyl vybrán typ pokoje!"
    Else
        ' Delete all rows with ID = selectedID
        Dim i As Long
        For i = tbl.ListRows.Count To 1 Step -1
            If tbl.ListRows(i).Range(1, 1).Value = selectedID Then
                tbl.ListRows(i).Delete
            End If
        Next i
        
        Name = Me.NameTB.Value
        DateArrival = Me.DateArrivalTB
        DateDeparture = Me.DateDepartureTB
        NumRooms = Me.NumRoomsTB
        numNights = Me.NumNightsTB
            
        ' Add new rows based on the number of rooms
        For rowIndex = 1 To NumRooms
            ' Insert a new row at the beginning of the table
            Set newRow = tbl.ListRows.Add(1)
            
            ' Update the table with the relevant information
            With newRow
                .Range(1).Value = selectedID
                .Range(2).Value = Name
                .Range(3).Value = DateArrival
                .Range(4).Value = DateDeparture
                .Range(5).Value = numNights
                .Range(6).Value = Me.Controls("RoomTypeTB" & rowIndex).Value
                .Range(7).Value = Me.Controls("NumEmployeeTB" & rowIndex).Value
                .Range(8).Value = Me.Controls("NumGuestTB" & rowIndex).Value
                .Range(9).Value = Me.Controls("PriceTB" & rowIndex).Value
            End With
        Next rowIndex
        Unload Me
    End If
End Sub

Private Sub DateArrivalTB_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    ' This event is triggered when you exit the DateArrivalTB (Arrival Date) field
    ' Validate and format the Arrival Date
    If Not IsValidDateFormat(Me.DateArrivalTB.Value) Then
        MsgBox "Invalid Arrival Date format. Please use dd.mm.yyyy", vbExclamation
        Me.DateArrivalTB.Value = "" ' Clear the TextBox
    End If
    
        ' Declare variables
    Dim DateArrival As Date
    Dim DateDeparture As Date
    Dim numNights As Integer
    
    ' Get values from UserForm
    DateArrival = Me.DateArrivalTB.Value
    DateDeparture = Me.DateDepartureTB.Value
    
    ' Calculate the number of nights
    numNights = DateDiff("d", DateArrival, DateDeparture)
    
    ' Update NumNightsTB with the calculated value
    Me.NumNightsTB.Value = numNights
    
    Dim i As Integer
    
    For i = 1 To 6
        CalculateRoomPrice (i)
    Next i
End Sub

Private Sub DateDepartureTB_Exit(ByVal Cancel As MSForms.ReturnBoolean)
    ' This event is triggered when you exit the DateDepartureTB (Departure Date) field
    ' Validate and format the Departure Date
    If Not IsValidDateFormat(Me.DateDepartureTB.Value) Then
        MsgBox "Invalid Departure Date format. Please use dd.mm.yyyy", vbExclamation
        Me.DateDepartureTB.Value = "" ' Clear the TextBox
    End If
    
    ' Declare variables
    Dim DateArrival As Date
    Dim DateDeparture As Date
    Dim numNights As Integer
    
    ' Get values from UserForm
    DateArrival = Me.DateArrivalTB.Value
    DateDeparture = Me.DateDepartureTB.Value
    
    ' Calculate the number of nights
    numNights = DateDiff("d", DateArrival, DateDeparture)
    
    ' Update NumNightsTB with the calculated value
    Me.NumNightsTB.Value = numNights
    
    Dim i As Integer
    
    For i = 1 To 6
        CalculateRoomPrice (i)
    Next i
End Sub

Private Function IsValidDateFormat(dateString As String) As Boolean
    ' This function checks if the date string is a valid date in the format dd.mm.yyyy
    
    ' Validate the date format
    On Error Resume Next
    Dim formattedDate As Date
    formattedDate = Format(CDate(dateString), "dd.mm.yyyy")
    On Error GoTo 0
    
    ' Check if the date is valid and has the correct format
    IsValidDateFormat = (IsDate(dateString) And (formattedDate = CDate(dateString)))
End Function

Private Sub ResetTextBoxes()
    ' Reset all TextBoxes to clear previous data
    Dim i As Integer
    For i = 1 To 6 ' Assuming you have a maximum of 10 rooms, adjust as needed
        Me.Controls("RoomTypeTB" & i).Value = ""
        Me.Controls("NumEmployeeTB" & i).Value = ""
        Me.Controls("NumGuestTB" & i).Value = ""
        Me.Controls("PriceTB" & i).Value = ""
    Next i
End Sub

Private Sub DisplaySelectedRooms()
    ' Display the number of selected rooms based on ComboBox selections
    Dim numSelectedRooms As Integer
    Dim i As Integer

    ' Count the selected rooms
    For i = 1 To 6
        If Me.Controls("RoomTypeTB" & i).Value <> "" Then
            numSelectedRooms = numSelectedRooms + 1
        End If
    Next i

    ' Display the result in a TextBox (change "NumRoomsTB" to your actual TextBox name)
    Me.NumRoomsTB.Value = numSelectedRooms
End Sub

Private Sub UpdateTotalPrice()
    Dim totalRoomPrice As Double
    Dim i As Integer

    ' Calculate the total price
    For i = 1 To 6
        If IsNumeric(Me.Controls("PriceTB" & i).Value) And Me.Controls("PriceTB" & i).Value <> "" Then
            totalRoomPrice = totalRoomPrice + CDbl(Me.Controls("PriceTB" & i).Value)
        End If
    Next i
    
    Me.PriceTotalTB.Value = totalRoomPrice
End Sub

Private Function CalculateRoomPrice(num As Double) As Double
    Dim roomType As String
    Dim numEmployee As Double
    Dim numGuest As Double
    Dim numNights As Double
    Dim pricePerEmployee As Double
    Dim pricePerGuest As Double
    
    
    Dim ws As Worksheet
    Set ws = ThisWorkbook.Sheets("Nastavení")
    
    Dim configTable As ListObject
    Set configTable = ws.ListObjects("Config")
    
    roomType = Me.Controls("RoomTypeTB" & num).Value
    numEmployee = val(Me.Controls("NumEmployeeTB" & num).Value)
    numGuest = val(Me.Controls("NumGuestTB" & num).Value)
    numNights = val(Me.Controls("NumNightsTB").Value)
    
    If roomType = "" Then
        Exit Function
    Else
        Dim rowIndex As Variant
        rowIndex = Application.Match(roomType, configTable.ListColumns("POKOJ").DataBodyRange, 0)
    
        If IsNumeric(rowIndex) Then
            pricePerEmployee = configTable.ListColumns("CENA Z").DataBodyRange(rowIndex).Value
            pricePerGuest = configTable.ListColumns("CENA N").DataBodyRange(rowIndex).Value
        Else
            MsgBox "Pokoj neexistuje. Pokud potøebujete pøidat nový pokoj, pøidejte ho v listu Nastavení", vbExclamation
            Exit Function
        End If
    End If
    
    Me.Controls("PriceTB" & num) = ((pricePerEmployee * numEmployee) + (pricePerGuest * numGuest)) * numNights
End Function

Private Function IsEmpty(textbox As MSForms.textbox) As Boolean
    IsEmpty = (Trim(textbox.Value) = "")
End Function

Private Sub FillRoomTypes(ByVal comboBox As MSForms.comboBox)
    Dim ws As Worksheet
    Dim configTable As ListObject
    Dim roomTypeCell As Range
    Dim roomType As Variant

    ' Set the worksheet and table
    Set ws = ThisWorkbook.Sheets("Nastavení")
    Set configTable = ws.ListObjects("Config")

    ' Assuming "RoomType" is the column in the Config table
    Set roomTypeCell = configTable.ListColumns("POKOJ").DataBodyRange

    ' Clear existing items in the ComboBox
    comboBox.Clear

    ' Add room types from the Config table to the ComboBox
    For Each roomType In roomTypeCell
        comboBox.AddItem roomType.Value
    Next roomType
End Sub
