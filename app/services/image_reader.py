import pytesseract

def read_image(image_path):
    text = pytesseract.image_to_string(image_path)
    parts = text.split("\n")
    info_dict = {
      "date": parts[4],
      "from": {
          "name": parts[11],
          "id": parts[13].split(" ")[1],
          "bank": parts[14],
          'account': parts[15].split(" ")[1]
      },
      "to": {
          "name": parts[19],
          "id": parts[21].split(" ")[1],
          "bank": parts[22],
          'account': parts[24].split(" ")[1]
      },
      "amount": parts[6]
    }
    return info_dict