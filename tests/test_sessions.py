import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sessions import decide, normalize_plate, normalize_name

IVANOV, PETROV = 'drv-ivanov', 'drv-petrov'
OPEN_BY_IVANOV = {'driver_id': IVANOV, 'driver_name': 'Иванов И. И.',
                  'started_at': '2026-10-06T08:12:00+03:00', 'start_mileage': 214400, 'start_moto': None}


def test_acceptance_free_vehicle_opens_row():
    d = decide('acceptance', 'truck', None, IVANOV, 214400, None)
    assert d.action == 'open' and d.http_status == 200


def test_acceptance_busy_vehicle_is_blocked():
    for driver in (IVANOV, PETROV):
        d = decide('acceptance', 'truck', OPEN_BY_IVANOV, driver, 214500, None)
        assert d.action == 'reject' and d.http_status == 409
        assert 'Иванов И. И.' in d.message and '06.10' in d.message


def test_return_same_driver_closes_with_distance():
    d = decide('return', 'truck', OPEN_BY_IVANOV, IVANOV, 215990, None)
    assert d.action == 'close' and d.flags == [] and d.distance == 1590


def test_return_other_driver_is_flagged():
    d = decide('return', 'truck', OPEN_BY_IVANOV, PETROV, 215000, None)
    assert d.action == 'close' and d.flags == ['other_driver'] and d.distance == 600


def test_return_without_acceptance():
    d = decide('return', 'truck', None, IVANOV, 215000, None)
    assert d.action == 'closed_no_acceptance' and d.flags == ['no_acceptance'] and d.distance is None


def test_return_mileage_below_acceptance_is_rejected():
    d = decide('return', 'truck', OPEN_BY_IVANOV, IVANOV, 214399, None)
    assert d.action == 'reject' and d.http_status == 400 and '214 400' in d.message


def test_return_same_mileage_is_zero_distance():
    assert decide('return', 'truck', OPEN_BY_IVANOV, IVANOV, 214400, None).distance == 0


def test_truck_requires_mileage():
    d = decide('acceptance', 'truck', None, IVANOV, None, None)
    assert d.action == 'reject' and d.http_status == 400


def test_trailer_without_mileage_and_moto_hours():
    open_trailer = {'driver_id': IVANOV, 'driver_name': 'Иванов', 'started_at': None,
                    'start_mileage': None, 'start_moto': 1200}
    assert decide('acceptance', 'trailer', None, IVANOV, None, 1200).action == 'open'
    d = decide('return', 'trailer', open_trailer, IVANOV, None, 1250)
    assert d.action == 'close' and d.moto_delta == 50 and d.distance is None
    assert decide('return', 'trailer', open_trailer, IVANOV, None, 1100).action == 'reject'
    # тент без моточасов
    d = decide('return', 'trailer', {**open_trailer, 'start_moto': None}, IVANOV, None, None)
    assert d.action == 'close' and d.moto_delta is None


def test_unknown_kind():
    assert decide('check', 'truck', None, IVANOV, 1, None).http_status == 400


def test_normalize_plate_layouts():
    assert normalize_plate('ах 5463-5') == normalize_plate('AX5463-5') == 'AX54635'
    assert normalize_plate('АХ5463-5') == 'AX54635'
    assert normalize_plate('') == ''


def test_normalize_name():
    assert normalize_name('  Иванов  Иван ИВАНОВИЧ ') == 'иванов иван иванович'
    assert normalize_name('Пётр') == normalize_name('Петр')
