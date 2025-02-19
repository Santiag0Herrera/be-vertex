# Backend Documentation

## 3. Obtaining Bank Data
To carry out transaction reconciliation, the system must have information on the client's bank movements. There are two main ways to obtain this data:

### **3.1. Manual Upload of Transactions**
Clients can manually upload their bank transactions to the system through:
- **CSV files** exported from their bank.
- **Data entry in the frontend**, where the user manually inputs relevant transactions.
- **Importing PDF files** with bank statements.

### **3.2. Future Integrations**
Since most banks do not offer public APIs, future versions will consider:
- **Bank scraping (automated with prior client authorization).**
- **Integrations with banks that provide private APIs, if possible.**
- **Connectors with accounting systems used by the client.**

---

## 4. API Definition and Endpoints
The backend API must expose reconciliation data clearly and accessibly. The defined endpoints allow interaction with the frontend and other external systems.

### **4.1. Available Endpoints**

#### **Authentication**
- `POST /auth/login` → Log in and obtain a JWT token.
- `POST /auth/register` → Register a new user.
- `POST /auth/refresh` → Renew authentication token.

#### **Receipt Upload**
- `POST /upload/image` → Upload a receipt image.
- `POST /upload/pdf` → Upload a receipt in PDF format.
- `GET /comprobantes/{id}` → Retrieve processed receipt information.

#### **Transaction Management**
- `GET /transactions` → List all uploaded transactions.
- `GET /transactions/{id}` → Retrieve details of a specific transaction.
- `POST /transactions` → Manually add a new transaction.
- `DELETE /transactions/{id}` → Delete a transaction.

#### **Bank Reconciliation**
- `POST /reconciliation` → Execute the reconciliation process.
- `GET /reconciliation/report` → Retrieve the reconciliation report.
- `GET /reconciliation/missing` → Check missing transactions.

#### **Export and Reports**
- `GET /reports/csv` → Export reconciled data in CSV format.
- `GET /reports/pdf` → Generate a reconciliation report in PDF format.

---

## 4.2. Security and Authorization
To ensure data access security, the API uses:
- **JWT** for user authentication.
- **Roles and permissions** to restrict access to sensitive functionalities.
- **Data validation** with Pydantic to prevent malicious inputs.

---

This documentation will be updated as new system features are added.

