# School Management for Odoo 19

A school management addon aimed at Kenyan schools running CBC (PP1 to Grade 12) and/or the legacy 8-4-4 secondary system (Form 1 to Form 4).

## Install

1. Copy the `school_management` folder into a directory on your Odoo `addons_path` (or unzip it there).
2. Restart Odoo, open **Apps**, click **Update Apps List**, search for "School Management" and install.
3. Dependencies (installed automatically): `mail`, `hr`, `account`, `portal`, `sms`.
4. Users with the *Settings* administrator right automatically get **School Administration: Administrator**. Give everyone else their roles under Settings > Users, in the **School** section. Each role (Teaching, Admissions & Records, School Fees, Library) is a separate selection, so one person can hold several.

## Roles

| Role | Can do |
|------|--------|
| Teacher | Classes, timetable, attendance, exams, mark entry, report cards |
| Registrar | Admissions, students, guardians, transport subscriptions, hostel allocation |
| Bursar / Accountant | Fee structures, invoice generation, student invoices (uses Odoo Accounting) |
| Librarian | Books and loans |
| Administrator | Everything, plus configuration and promotion |

## First-time setup

0. **Configuration > Settings** (or Settings > School): optionally enter the **School name** and upload the **School logo**. The name replaces "School" on the app tile and appears on the dashboard, report cards, fee invoices and the parent portal; leave it empty to keep the default. The logo is the company logo, printed in the letterhead of all documents. Both are per company.
1. **Configuration > Academic Years**: create the year, open it, add the three terms (with next-term opening dates).
2. **Configuration > Subjects** and **Lesson Periods**.
3. **Staff**: add teaching and non-teaching staff (they are `hr.employee` records with a *School Role*). Roles such as Teacher, Principal, Librarian, Matron, Patron, Driver, Bursar or Cook are managed under **Configuration > Staff Roles**; each is Teaching or Non-Teaching. Teaching roles make the person available as class or subject teacher. Staff roles are HR records; to let someone log in (e.g. the librarian), create a user and give them the matching school access role.
4. **Academics > Classes**: create classes/streams and allocate subjects and teachers.
5. **Fees > Fee Structures**: set amounts per grade level (and per term / day-boarding if needed). Fee items are services; edit or add them under Accounting products. Set an income account on the products or product category.
6. **Admissions > Applications**: submit, accept, then *Enrol Student* to create the student and guardian. An existing guardian (e.g. a sibling's parent) is reused when the National ID or email matches.
7. **Students > Parents & Guardians** lists only contacts flagged as guardians, with a school-specific form (National ID, occupation, contact details, children). The guardian picker on a student's Guardians tab offers only these contacts, so staff and company contacts are not shown. Creating a guardian from that picker flags it automatically.

## Dashboard

Opening the **School** app lands on the dashboard (also under School > Dashboard). It shows enrolment, today's attendance, fee collection for the selected term, outstanding fees, staff, pending admissions and overdue books, plus charts (enrolment by grade, attendance trend, fees by class, mean score by class) and "needs attention" lists (registers not taken today, exams being marked, highest balances, hostel/transport capacity). Cards, chart bars and list rows open the underlying records. Each user only sees the sections their school role can open: fees for the bursar, academics for teachers, and so on.

## Term workflow

* **Fees > Generate Invoices**: choose term and classes. Invoices are created per student, billed to the fee-paying guardian, with bursary discount and active transport route fee applied. Students already invoiced for the term are skipped.
* **Academics > Timetable** opens a weekly grid (days × lesson periods, breaks as bands) for a class or a teacher. Click an empty slot to add a lesson, a lesson to edit it; Grid/List toggles to the classic list. Clashes (a class or teacher booked twice in a period) are refused. *Print* downloads the timetable shown (class or teacher, selected year) as an A4 landscape PDF.
* **Academics > Attendance**: one register per class per day; confirm it when done.
* **Exams > Exams**: create the exam, *Generate Mark Sheet*, enter marks under **Mark Entry**. Grades are computed from the CBC 8-level scale or KCSE scale depending on the class's grade level. A row counts as marked once a mark is typed in; tick *Marked* to record a genuine 0, or *Absent*. *Mark Done* is refused while any row is unmarked, and a Done exam's marks are locked until it is reset.
* **Exams > Generate Report Cards**: builds or refreshes the draft cards for a class and term from exams marked *Done* only (subject averages weighted by exam weight, mean grade, class position, attendance). Published cards are not recomputed; unpublish to refresh. Edit comments, then *Publish*.
* **Students > Year-End Rollover** at year end: create the new academic year first, then pick From/To year. Every class is listed with a suggested action (promote to the next level and same stream, graduate final levels, skip empty classes); missing classes for the new year are created with the old class's subjects and teachers. Pick repeaters per class. Optionally archive last year's classes and close/open the years. **Promote Students** remains for moving a single class.

## Parent portal

Link a guardian contact to a portal user (Contacts > Action > Grant portal access). Parents then see a **My Children** card on their portal home (`/my/children`) showing their children, fee balance and published report cards (PDF), and `/my/invoices` for the invoices. Every guardian of a student sees that student's posted fee invoices under `/my/invoices`, not only the guardian billed as fee payer.

To set or reset a parent's password from the backend: Settings > Users, remove the default "Internal Users" filter (or filter on Portal Users), open or tick the parent, then Action > Change Password. The parent can also use "Reset Password" on the login page.

## Fee balances and partial payments

* Parents can pay in instalments of any amount. A partly paid invoice stays open with its remaining amount.
* A student's **fee balance** covers all terms: unpaid invoices, less advance payments, overpayments and unused credit notes. A negative balance means the account is in credit and is shown as "In credit" on the portal.
* Credit is used automatically: when a fee invoice is posted, the student's unused payments and credit notes are applied to it, oldest first. A credit note pays the invoice it reverses first. Payments registered on a student's invoice are linked to the student automatically; when you create a payment directly (an advance), set its **Student** field so it counts.
* Student fee invoices print a **student account** box under the totals: balance from other invoices (or credit), amount due on this invoice, and total outstanding as at the print date.
* **Fee Statement** (Print menu on a student, bursar only, and a download on the parent portal) lists every invoice, credit note and payment with a running balance. It always ends on the student's fee balance.
* Use bank or M-Pesa journals whose incoming payment method has an **Outstanding Receipts account**. Without one, Odoo 19 records payments without a journal entry and the invoice only shows as paid after bank reconciliation. The balance already deducts such payments when they carry the student.

## Announcements and messages to parents

* **Communication > Announcements** (registrar and administrator; others can read): write a notice for all parents, chosen grade levels or chosen classes, set the publish date and optionally an end date, mark it *Important* to pin it, and *Publish*. Parents of enrolled students in the audience see it at the top of **My Children** and under **School Announcements** on the portal; unread ones are marked *New*. Tick *Also Send by Email* to email it on publishing. The *Read* button shows who has opened it. Add files (circulars, letters, fee schedules) under *Attachments*; parents open or download them from the announcement page, and they are attached to the email.
* **Communication > Guardian Messages** (teachers, registrar, bursar; a teacher sees only the conversations they started or send, the school office sees all): a private conversation with one guardian, optionally about one of their children. Write the first message and click *Send*; the guardian gets an email and sees it under **Messages from School** on the portal, where they can reply. Continue in the chatter with *Send message*; a *Log note* stays internal. *Close Conversation* turns off replies. To find a guardian quickly, pick a *Grade Level* and *Class* first: the Student and Guardian lists then show only that class. Choosing a student fills in their primary guardian (students can be searched by name, admission number or UPI). The list can be filtered and grouped by class and grade level. A student form has a **Message Guardian** button that starts a message to the primary guardian.

## SMS

SMS go through Odoo's standard SMS engine. Without anything else they use Odoo IAP credits; install the **SMS Gateways** addon (`livecrib_sms_gateway`) to send through Africa's Talking, Advanta or any HTTP SMS API instead (see its README). Numbers are taken from the guardian's *Phone* and formatted with the company country (Kenya: `0712...` becomes `+254712...`); numbers on the phone blacklist are skipped. Sent and failed SMS are under Settings > Technical > Phone / SMS > SMS.

* **Announcements**: tick *Also Send by SMS* and write the short *SMS Text* (a counter shows the characters and number of SMS). On publishing, one SMS per guardian phone number is queued and sent in the background; *SMS Queued* shows how many.
* **Guardian Messages**: tick *Also Notify by SMS* before *Send*. The guardian gets a short SMS with the subject and a link to read and reply on the portal; the SMS and its delivery status are logged on the conversation.
* **Students**: select students in the list (for example with the **Owes Fees** filter, bursar only) and use Action > **Send SMS to Guardians**; pick the template **School: Fee Balance Reminder** to text each primary guardian the student's balance, or write your own text. On a student form, Action > **Send SMS to Guardian** texts the primary guardian. Templates are under Settings > Technical > Phone / SMS > SMS Templates.

## Payments and M-Pesa

Fees are standard customer invoices, paid from Accounting with **Register Payment**. Payment methods set up under Point of Sale are not used for invoices; only their journal is. To record an M-Pesa payment by hand, choose the M-Pesa journal and enter the M-Pesa code in the memo.

For automatic M-Pesa Paybill payments, install the **School M-Pesa Fee Payments** bridge (`school_mpesa`, needs `pos_mpesa_payment`). Parents pay with the admission number as the account number, and Safaricom confirmations are matched to the student and paid against their fee invoices, either automatically or after the bursar reviews them under Fees > M-Pesa Receipts. See its README.

## Notes

* Grade scales are editable data (Configuration > Grade Scales). Only one scale per education system may be active. Changing a scale does not retroactively regrade existing results; edit a mark or recompute cards to refresh.
* Odoo 19 conventions used: `res.groups.privilege` for roles, `models.Constraint` for uniqueness, `self.env._` for translations, and `hr.employee.public` exposing `is_teacher` for users without HR rights. Checked against the 19.0 source, but not yet run on a live instance. Install on a test database first.
