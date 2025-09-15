Attribute VB_Name = "Module2"
Sub GenerateCoupon()
    ' Deklarace promìnných pro práci s hodnotami z tabulky a cílovým listem
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
    
    On Error Resume Next ' Zapne potlaèení chyb (pokraèuje i pøi chybì)

    ' Sestavení úplné cesty k existujícímu souboru s poukazem
    workbookPath = ThisWorkbook.Path & "\Poukaz_dobrejov.xlsm" ' Cesta k souboru (název mùžeš v pøípadì potøeby zmìnit)

    ' Otevøení existujícího sešitu s poukazem
    Set existingWorkbook = Workbooks.Open(workbookPath)
    On Error GoTo 0 ' Vypne potlaèení chyb (vrátí standardní zpracování chyb)

    reservationFound = False ' Výchozí stav: rezervace zatím nenalezena

    ' Kontrola, zda se sešit podaøilo otevøít
    If existingWorkbook Is Nothing Then
        ' Soubor nebyl nalezen – vyžádat od uživatele výbìr souboru
        Dim fileDialog As Object
        Set fileDialog = Application.fileDialog(msoFileDialogFilePicker)
        
        With fileDialog
            .Title = "Select Workbook" ' Titulek dialogu
            .Filters.Add "Excel Files", "*.xls; *.xlsx; *.xlsm", 1 ' Filtrování pouze na excelové soubory
            .ButtonName = "Select" ' Popisek tlaèítka

            If .Show = -1 Then ' Uživatel vybral soubor (stiskl OK)
                Set existingWorkbook = Workbooks.Open(.SelectedItems(1)) ' Otevøít vybraný soubor
            Else
                MsgBox "No file selected. Exiting macro.", vbExclamation ' Upozornìní, že nebyl vybrán soubor
                Exit Sub ' Ukonèit makro
            End If
        End With
    End If

    ' Nastavení cílového listu v otevøeném sešitu (list s poukazem)
    Set destinationSheet = existingWorkbook.Sheets("Poukaz") ' Zmìò název listu dle skuteènosti, pokud je jiný

    ' Nastavení zdrojového listu a tabulky s rezervacemi v tomto sešitu
    Set ws = ThisWorkbook.Sheets("Rezervace") ' List, kde je tabulka s rezervacemi
    Set tbl = ws.ListObjects("Assignments") ' Excelová tabulka se jménem "Assignments"

    ' Získání ID rezervace od uživatele
    reservationID = InputBox("Zadejte ID rezervace:")

    ' Poèáteèní øádek, od kterého se budou zapisovat osoby do cílového listu
    nextRow = 17

    ' Projít všechny øádky v tabulce rezervací
    For Each row In tbl.ListRows
        ' Kontrola shody ID rezervace v prvním sloupci tabulky
        If row.Range(1, 1).Value = reservationID Then
            reservationFound = True ' Rezervace nalezena

            ' Jednorázovì naèíst základní údaje o rezervaci (jen pokud ještì nejsou nastavené)
            If Len(guestName) = 0 Then
                reservationID = row.Range(1, 1).Value ' ID rezervace
                guestName = row.Range(1, 2).Value ' Jméno hosta
                arrivalDate = row.Range(1, 3).Value ' Datum pøíjezdu
                departureDate = row.Range(1, 4).Value ' Datum odjezdu
                numberOfNights = row.Range(1, 5).Value ' Poèet nocí (pøedpoklad: sloupec 5)
            End If

            ' Zjištìní poètu osob (Z + N) – pøedpoklad: Z ve sloupci 7, N ve sloupci 8
            Dim numberOfPeople As Integer
            numberOfPeople = row.Range(1, 7).Value + row.Range(1, 8).Value

            ' Zapsat ID rezervace na definované místo v cílovém listu (ø. 3, sl. 5 = E3)
            destinationSheet.Cells(3, 5).Value = reservationID

            ' Vytvoøit samostatný øádek pro každou osobu v poukazu
            For i = 1 To numberOfPeople
                ' Vyplnit základní údaje do cílového listu (jméno a data)
                destinationSheet.Cells(nextRow, 2).Value = guestName ' Sloupec B: jméno hosta
                destinationSheet.Cells(nextRow, 10).Value = arrivalDate ' Sloupec J: pøíjezd
                destinationSheet.Cells(nextRow, 11).Value = departureDate ' Sloupec K: odjezd
                ' destinationSheet.Cells(nextRow, 12).Value = numberOfNights ' Sloupec L: poèet nocí (aktuálnì zakomentováno)

                ' Urèení typu osoby (ZA/NA nebo Z/N) podle typu pokoje a poøadí osoby
                Dim personType As String
                Dim roomType As String
                roomType = row.Range(1, 6).Value ' Pøedpoklad: typ pokoje je ve sloupci 6

                ' Pokud je typ pokoje "Apartmán...", rozlišení na "ZA" a "NA"
                If Left(roomType, 8) = "Apartmán" Then
                    If i <= row.Range(1, 7).Value Then
                        personType = "ZA" ' Základní (apartmán) osoba
                    Else
                        personType = "NA" ' Nezákladní (apartmán) osoba
                    End If
                Else
                    ' Jinak používat zkratky "Z" a "N" podle toho, zda je osoba v rámci Z
                    personType = IIf(i <= row.Range(1, 7).Value, "Z", "N")
                End If

                ' Zapsat typ osoby a typ pokoje do cílového listu
                destinationSheet.Cells(nextRow, 1).Value = personType ' Sloupec A: typ osoby
                destinationSheet.Cells(nextRow, 5).Value = row.Range(1, 6).Value ' Sloupec E: typ/èíslo pokoje

                nextRow = nextRow + 1 ' Posunout se na další øádek pro další osobu
            Next i
        End If
    Next row

    ' Po prùchodu tabulkou: pokud rezervace nenalezena, informovat uživatele a zavøít soubor bez uložení
    If Not reservationFound Then
        MsgBox "ID rezervace nenalezeno." ' Zpráva o nenalezení
        existingWorkbook.Close SaveChanges:=False ' Zavøít otevøený sešit bez uložení
        Exit Sub ' Ukonèit makro
    Else
        ' Jinak potvrdit úspìšné vytvoøení poukazu
        MsgBox "Poukaz úspìšnì vytvoøen."
    End If
End Sub
