Attribute VB_Name = "Module1"
Sub tla��tko4_Kliknut�()
    ' Deklarace prom�nn� UniqueID jako textov� �et�zec
    Dim UniqueID As String
    
    ' Zavol�n� funkce GenerateUniqueID a ulo�en� v�sledku do prom�nn� UniqueID
    UniqueID = GenerateUniqueID()
    
    ' P�i�azen� vygenerovan�ho ID do textov�ho pole IdentTB na formul��i BookingForm
    BookingForm.IdentTB.Value = UniqueID
    
    ' Zobrazen� formul��e BookingForm u�ivateli
    BookingForm.Show
End Sub

Function GenerateUniqueID() As String
    ' Funkce vytvo�� unik�tn� ID na z�klad� aktu�ln�ho data a �asu
    
    ' Format vrac� �asov� raz�tko ve form�tu RRRRMMDDHHMMSS
    ' (rok, m�s�c, den, hodina, minuta, sekunda)
    GenerateUniqueID = Format(Now, "yyyymmddhhmmss")
End Function
