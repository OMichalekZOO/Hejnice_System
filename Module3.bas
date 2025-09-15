Attribute VB_Name = "Module3"
Sub EditByID()
    Dim userInput As String
    Dim notFound As Boolean
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim row As ListRow
    
    Set ws = Worksheets("Rezervace")
    Set tbl = ws.ListObjects("Assignments")
    
    notFound = True
    userInput = InputBox("Zadejte ID rezervace:", "Input Dialog")
    
    For Each row In tbl.ListRows
        If row.Range(1, 1).Value = userInput Then
            notFound = False
        End If
    Next row

    If notFound Then
        MsgBox "Záznam s tímto ID nebyl nalezen."
        Exit Sub
    End If
    
    If userInput = "" Then
        Exit Sub
    End If
    
    EditForm.BookingIDCB.Value = userInput
    EditForm.Show
End Sub
