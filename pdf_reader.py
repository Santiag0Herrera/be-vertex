import pdfplumber
with pdfplumber.open("./comprobante.pdf") as pdf:
    page = pdf.pages[0]
    text = page.extract_text()
    parts = text.split("\n")
    info_dict = {
      "from": {
          "name": parts[5],
          "id": parts[6].split(" ")[1],
          "bank": parts[7],
          'account': parts[8].split(" ")[1]
      },
      "to": {
          "name": parts[10],
          "id": parts[11].split(" ")[1],
          "bank": parts[13],
          'account': parts[14].split(" ")[1]
      },
      "amount": parts[2]
    }