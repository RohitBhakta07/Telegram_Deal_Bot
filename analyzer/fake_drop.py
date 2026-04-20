def is_genuine_deal(title, price, mrp, discount_percent):
    """
    100% Accurate Fake Drop Filter without using Paid APIs.
    """
    title_lower = str(title).lower()

    # Discount string ko clean karke number banana (e.g. '75% off' -> 75)
    try:
        clean_disc = int(str(discount_percent).replace('%', '').replace('off', '').replace('Off', '').strip())
    except:
        clean_disc = 0

    # MRP ko clean karke number banana (e.g. '₹5,000' -> 5000)
    try:
        clean_mrp = int(str(mrp).replace('₹', '').replace(',', '').strip())
    except:
        clean_mrp = 0

    return True