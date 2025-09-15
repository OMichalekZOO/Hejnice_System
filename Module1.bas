Attribute VB_Name = "Module1"
Sub tlaèítko4_Kliknutí()
    ' Deklarace promìnné UniqueID jako textový øetìzec
    Dim UniqueID As String
    
    ' Zavolání funkce GenerateUniqueID a uložení výsledku do promìnné UniqueID
    UniqueID = GenerateUniqueID()
    
    ' Pøiøazení vygenerovaného ID do textového pole IdentTB na formuláøi BookingForm
    BookingForm.IdentTB.Value = UniqueID
    
    ' Zobrazení formuláøe BookingForm uživateli
    BookingForm.Show
End Sub

Function GenerateUniqueID() As String
    ' Funkce vytvoøí unikátní ID na základì aktuálního data a èasu
    
    ' Format vrací èasové razítko ve formátu RRRRMMDDHHMMSS
    ' (rok, mìsíc, den, hodina, minuta, sekunda)
    GenerateUniqueID = Format(Now, "yyyymmddhhmmss")
End Function
