{
    'name': 'Hang Heung POS Partner Form Simplify',
    'version': '1.0.0',
    'category': 'Point of Sale',
    'summary': 'Hide non-essential res.partner fields in the POS edit dialog',
    'description': """
        When the partner form is opened from the POS interface (create or edit
        a contact), drop a set of fields that are not useful at the counter:
        Contact No., Alternative Name, Credit Limit, CRDR Due Days, Customer
        Category, Purchase Auto Confirm, Occupation, Title, Terms, Vendor,
        B2B Customer, Internal Contact.

        The backend partner form (Settings, Contacts app) is unchanged — the
        hiding is gated by a `from_pos` context key set only by the POS
        editPartner flow.
    """,
    'author': 'Lau Siu Hin',
    'depends': ['point_of_sale', 'recreate_HangHeung'],
    'data': [
        'views/res_partner_pos_form.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hh_pos_partner_form/static/src/js/pos_store.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
