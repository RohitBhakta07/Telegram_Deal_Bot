"""Tests for database manager module."""
import os
import pytest
from database import db_manager


@pytest.fixture
def temp_db(tmp_path):
    """Use isolated temp database for testing."""
    db_path = tmp_path / "test.db"
    original_path = db_manager.DB_PATH
    db_manager.DB_PATH = str(db_path)
    db_manager.init_db()
    yield db_path
    db_manager.DB_PATH = original_path


class TestInit:
    def test_db_creates_tables(self, temp_db):
        """Database file should exist after init."""
        assert os.path.exists(temp_db)

    def test_settings_read_write(self, temp_db):
        """Should be able to write and read settings."""
        db_manager.update_setting('TEST_KEY', 'TEST_VALUE')
        assert db_manager.get_setting('TEST_KEY') == 'TEST_VALUE'

    def test_default_admin_exists(self, temp_db):
        """Default admin should be created on init."""
        username = db_manager.get_admin_username()
        assert username is not None


class TestAuthentication:
    def test_default_admin_has_no_known_password(self, temp_db):
        """Fresh databases must not expose a predictable login."""
        assert not db_manager.verify_admin('admin', 'admin123')

    def test_verify_wrong_password(self, temp_db):
        """Wrong password should fail."""
        assert not db_manager.verify_admin('admin', 'wrongpass')

    def test_verify_nonexistent_user(self, temp_db):
        """Non-existent user should fail."""
        assert not db_manager.verify_admin('ghost', 'pass')

    def test_password_update(self, temp_db):
        """Password should be updatable and verifiable."""
        db_manager.update_admin_password('admin', 'newpassword123')
        assert db_manager.verify_admin('admin', 'newpassword123')
        assert not db_manager.verify_admin('admin', 'admin123')

    def test_password_policy_is_enforced_in_database_layer(self, temp_db):
        with pytest.raises(ValueError):
            db_manager.update_admin_password('admin', 'ab')


class TestCategories:
    def test_add_category(self, temp_db):
        """Should add and retrieve a category."""
        db_manager.add_category('Test', 'keyword1, keyword2', 50, 'HIGH', 'hot_deal')
        cats = db_manager.get_all_categories()
        assert len(cats) >= 1
        assert cats[0][1] == 'Test'

    def test_category_default_priority(self, temp_db):
        """Default priority should be MEDIUM."""
        db_manager.add_category('NoPrio', 'kw1', 30)
        cats = db_manager.get_all_categories()
        found = [c for c in cats if c[1] == 'NoPrio']
        assert found
        assert found[0][4] == 'MEDIUM'

    def test_delete_category(self, temp_db):
        """Should delete a category by id."""
        db_manager.add_category('ToDelete', 'kw', 40)
        cats = db_manager.get_all_categories()
        cat_id = cats[0][0]
        db_manager.delete_category(cat_id)
        assert len(db_manager.get_all_categories()) == 0

    def test_update_category(self, temp_db):
        """Should update a category."""
        db_manager.add_category('Original', 'kw1', 40)
        cats = db_manager.get_all_categories()
        cat_id = cats[0][0]
        db_manager.update_category(cat_id, 'Updated', 'kw1, kw2', 50, 'HIGH', 'mega_loot')
        updated = db_manager.get_all_categories()
        assert updated[0][1] == 'Updated'
        assert updated[0][3] == 50
        assert updated[0][4] == 'HIGH'


class TestFlashKeywords:
    def test_add_flash(self, temp_db):
        """Should add and retrieve flash keywords."""
        db_manager.add_flash_keyword('iphone', 80)
        items = db_manager.get_all_flash_keywords()
        assert len(items) >= 1
        assert items[0][1] == 'iphone'

    def test_delete_flash(self, temp_db):
        """Should delete flash keyword."""
        db_manager.add_flash_keyword('test', 50)
        items = db_manager.get_all_flash_keywords()
        kid = items[0][0]
        db_manager.delete_flash_keyword(kid)
        assert len(db_manager.get_all_flash_keywords()) == 0


class TestChannels:
    def test_add_channel(self, temp_db):
        """Should add a channel."""
        db_manager.add_channel('@test', 'TestCh')
        assert len(db_manager.get_all_channels()) == 1

    def test_duplicate_channel(self, temp_db):
        """Duplicate channel should fail silently."""
        db_manager.add_channel('@dup', 'First')
        db_manager.add_channel('@dup', 'Second')
        assert len(db_manager.get_all_channels()) == 1

    def test_delete_channel(self, temp_db):
        """Should delete a channel."""
        db_manager.add_channel('@del', 'DeleteMe')
        db_manager.delete_channel('@del')
        assert len(db_manager.get_all_channels()) == 0


class TestDeals:
    def test_save_deal(self, temp_db):
        """Should save a deal."""
        db_manager.save_deal('Test Deal', 'http://link1', 'http://aff1', 'General')
        assert db_manager.get_total_deals_count() >= 1

    def test_duplicate_link(self, temp_db):
        """Duplicate link should not raise error."""
        db_manager.save_deal('D1', 'http://dup', 'http://aff', 'G')
        db_manager.save_deal('D2', 'http://dup', 'http://aff2', 'G')
        assert db_manager.get_total_deals_count() == 1

    def test_is_link_sent(self, temp_db):
        """Should detect already-sent links."""
        db_manager.save_deal('D', 'http://unique', 'http://aff', 'G')
        assert db_manager.is_link_already_sent('http://unique')
        assert not db_manager.is_link_already_sent('http://nonexistent')

    def test_clear_all_deals(self, temp_db):
        """Should clear all deals."""
        db_manager.save_deal('D', 'http://l', 'http://a', 'G')
        db_manager.clear_all_deals()
        assert db_manager.get_total_deals_count() == 0


class TestPriorityWeights:
    def test_normalize_priority(self):
        assert db_manager.normalize_priority('HIGH') == 'HIGH'
        assert db_manager.normalize_priority('low') == 'LOW'
        assert db_manager.normalize_priority('invalid') == 'MEDIUM'
        assert db_manager.normalize_priority('') == 'MEDIUM'
        assert db_manager.normalize_priority(None) == 'MEDIUM'

    def test_priority_weights(self):
        assert db_manager.get_priority_weight('HIGH') == 4
        assert db_manager.get_priority_weight('MEDIUM') == 2
        assert db_manager.get_priority_weight('LOW') == 1

    def test_keyword_weights(self, temp_db):
        """Higher priority categories should give higher keyword weights."""
        db_manager.add_category('High', 'kw1, kw2', 50, 'HIGH')
        db_manager.add_category('Low', 'kw2, kw3', 30, 'LOW')
        cats = db_manager.get_all_categories()
        weights = db_manager.build_keyword_weights(cats)
        # kw2 appears in both HIGH and LOW, should get max (4)
        assert weights.get('kw2') == 4
        assert weights.get('kw1') == 4
        assert weights.get('kw3') == 1

    def test_order_by_priority(self, temp_db):
        """HIGH priority categories should appear before LOW."""
        db_manager.add_category('LowPrio', 'lkw', 10, 'LOW')
        db_manager.add_category('HighPrio', 'hkw', 10, 'HIGH')
        cats = db_manager.get_all_categories()
        ordered = db_manager.order_categories_by_priority(cats)
        # HIGH priority should come first
        assert ordered[0][1] == 'HighPrio'
