Attribute VB_Name = "Module2"
Sub GenerateCoupon()
    ' Deklarace prom�nn�ch pro pr�ci s hodnotami z tabulky a c�lov�m listem
    Dim reservationID As String
    Dim ws As Worksheet
    Dim tbl As ListObject
    Dim row As ListRow
    Dim guestName As String
    Dim arrivalDate As String
    Dim departureDate As String
    Dim numberOfNights As Integer
    Dim existingWorkbook As Workbook
    Dim destinationSheet As Worksheet
    Dim nextRow As Long
    Dim reservationFound As Boolean
    
    On Error Resume Next ' Zapne potla�en� chyb (pokra�uje i p�i chyb�)

    ' Sestaven� �pln� cesty k existuj�c�mu souboru s poukazem
    workbookPath = ThisWorkbook.Path & "\Poukaz_dobrejov.xlsm" ' Cesta k souboru (n�zev m��e� v p��pad� pot�eby zm�nit)

    ' Otev�en� existuj�c�ho se�itu s poukazem
    Set existingWorkbook = Workbooks.Open(workbookPath)
    On Error GoTo 0 ' Vypne potla�en� chyb (vr�t� standardn� zpracov�n� chyb)

    reservationFound = False ' V�choz� stav: rezervace zat�m nenalezena

    ' Kontrola, zda se se�it poda�ilo otev��t
    If existingWorkbook Is Nothing Then
        ' Soubor nebyl nalezen � vy��dat od u�ivatele v�b�r souboru
        Dim fileDialog As Object
        Set fileDialog = Application.fileDialog(msoFileDialogFilePicker)
        
        With fileDialog
            .Title = "Select Workbook" ' Titulek dialogu
            .Filters.Add "Excel Files", "*.xls; *.xlsx; *.xlsm", 1 ' Filtrov�n� pouze na excelov� soubory
            .ButtonName = "Select" ' Popisek tla��tka

            If .Show = -1 Then ' U�ivatel vybral soubor (stiskl OK)
                Set existingWorkbook = Workbooks.Open(.SelectedItems(1)) ' Otev��t vybran� soubor
            Else
                MsgBox "No file selected. Exiting macro.", vbExclamation ' Upozorn�n�, �e nebyl vybr�n soubor
                Exit Sub ' Ukon�it makro
            End If
        End With
    End If

    ' Nastaven� c�lov�ho listu v otev�en�m se�itu (list s poukazem)
    Set destinationSheet = existingWorkbook.Sheets("Poukaz") ' Zm�� n�zev listu dle skute�nosti, pokud je jin�

    ' Nastaven� zdrojov�ho listu a tabulky s rezervacemi v tomto se�itu
    Set ws = ThisWorkbook.Sheets("Rezervace") ' List, kde je tabulka s rezervacemi
    Set tbl = ws.ListObjects("Assignments") ' Excelov� tabulka se jm�nem "Assignments"

    ' Z�sk�n� ID rezervace od u�ivatele
    reservationID = InputBox("Zadejte ID rezervace:")

    ' Po��te�n� ��dek, od kter�ho se budou zapisovat osoby do c�lov�ho listu
    nextRow = 17

    ' Proj�t v�echny ��dky v tabulce rezervac�
    For Each row In tbl.ListRows
        ' Kontrola shody ID rezervace v prvn�m sloupci tabulky
        If row.Range(1, 1).Value = reservationID Then
            reservationFound = True ' Rezervace nalezena

            ' Jednor�zov� na��st z�kladn� �daje o rezervaci (jen pokud je�t� nejsou nastaven�)
            If Len(guestName) = 0 Then
                reservationID = row.Range(1, 1).Value ' ID rezervace
                guestName = row.Range(1, 2).Value ' Jm�no hosta
                arrivalDate = row.Range(1, 3).Value ' Datum p��jezdu
                departureDate = row.Range(1, 4).Value ' Datum odjezdu
                numberOfNights = row.Range(1, 5).Value ' Po�et noc� (p�edpoklad: sloupec 5)
            End If

            ' Zji�t�n� po�tu osob (Z + N) � p�edpoklad: Z ve sloupci 7, N ve sloupci 8
            Dim numberOfPeople As Integer
            numberOfPeople = row.Range(1, 7).Value + row.Range(1, 8).Value

            ' Zapsat ID rezervace na definovan� m�sto v c�lov�m listu (�. 3, sl. 5 = E3)
            destinationSheet.Cells(3, 5).Value = reservationID

            ' Vytvo�it samostatn� ��dek pro ka�dou osobu v poukazu
            For i = 1 To numberOfPeople
                ' Vyplnit z�kladn� �daje do c�lov�ho listu (jm�no a data)
                destinationSheet.Cells(nextRow, 2).Value = guestName ' Sloupec B: jm�no hosta
                destinationSheet.Cells(nextRow, 10).Value = arrivalDate ' Sloupec J: p��jezd
                destinationSheet.Cells(nextRow, 11).Value = departureDate ' Sloupec K: odjezd
                ' destinationSheet.Cells(nextRow, 12).Value = numberOfNights ' Sloupec L: po�et noc� (aktu�ln� zakomentov�no)

                ' Ur�en� typu osoby (ZA/NA nebo Z/N) podle typu pokoje a po�ad� osoby
                Dim personType As String
                Dim roomType As String
                roomType = row.Range(1, 6).Value ' P�edpoklad: typ pokoje je ve sloupci 6

                ' Pokud je typ pokoje "Apartm�n...", rozli�en� na "ZA" a "NA"
                If Left(roomType, 8) = "Apartm�n" Then
                    If i <= row.Range(1, 7).Value Then
                        personType = "ZA" ' Z�kladn� (apartm�n) osoba
                    Else
                        personType = "NA" ' Nez�kladn� (apartm�n) osoba
                    End If
                Else
                    ' Jinak pou��vat zkratky "Z" a "N" podle toho, zda je osoba v r�mci Z
                    personType = IIf(i <= row.Range(1, 7).Value, "Z", "N")
                End If

                ' Zapsat typ osoby a typ pokoje do c�lov�ho listu
                destinationSheet.Cells(nextRow, 1).Value = personType ' Sloupec A: typ osoby
                destinationSheet.Cells(nextRow, 5).Value = row.Range(1, 6).Value ' Sloupec E: typ/��slo pokoje

                nextRow = nextRow + 1 ' Posunout se na dal�� ��dek pro dal�� osobu
            Next i
        End If
    Next row

    ' Po pr�chodu tabulkou: pokud rezervace nenalezena, informovat u�ivatele a zav��t soubor bez ulo�en�
    If Not reservationFound Then
        MsgBox "ID rezervace nenalezeno." ' Zpr�va o nenalezen�
        existingWorkbook.Close SaveChanges:=False ' Zav��t otev�en� se�it bez ulo�en�
        Exit Sub ' Ukon�it makro
    Else
        ' Jinak potvrdit �sp�n� vytvo�en� poukazu
        MsgBox "Poukaz �sp�n� vytvo�en."
    End If
End Sub
