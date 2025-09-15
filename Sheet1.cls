VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Sheet1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Function GenerateUniqueID() As String
    ' This function generates a unique ID based on the current date and time
    GenerateUniqueID = Format(Now, "yyyymmddhhmmss")
End Function

Private Sub DeleteRowForm_Click()
    CancelForm.Show
End Sub

Private Sub OpenBookingForm_Click()
    Dim UniqueID As String
    
    UniqueID = GenerateUniqueID()
    
    BookingForm.IdentTB.Value = UniqueID
    BookingForm.Show
End Sub
