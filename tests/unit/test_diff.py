"""Tests for diff parsing."""

from blast_radius.diff import ChangedHunk, parse_diff


SAMPLE_DIFF = """\
diff --git a/utils.py b/utils.py
index abc123..def456 100644
--- a/utils.py
+++ b/utils.py
@@ -1,5 +1,6 @@
-def validate_order(order_data):
+def validate_order(order_data, strict=False):
     \"\"\"Validate order data before processing.\"\"\"
     if not order_data.get("items"):
+        if strict:
+            raise TypeError("Items must be a list")
         raise ValueError("Order must have items")
"""

SAMPLE_DIFF_NEW_FILE = """\
diff --git a/new_module.py b/new_module.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,5 @@
+def new_function():
+    pass
"""

SAMPLE_DIFF_DELETED = """\
diff --git a/old_module.py b/old_module.py
deleted file mode 100644
index abc1234..0000000
--- a/old_module.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def old_function():
-    pass
"""

SAMPLE_DIFF_RENAME = """\
diff --git a/old_name.py b/new_name.py
similarity index 95%
rename from old_name.py
rename to new_name.py
index abc123..def456 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
-def foo():
+def foo(x):
     pass
"""

SAMPLE_DIFF_MULTI_HUNK = """\
diff --git a/service.py b/service.py
index abc123..def456 100644
--- a/service.py
+++ b/service.py
@@ -3,4 +3,5 @@
 def create_order(user_id, order_data):
     validate_order(order_data)
+    log("creating order")
     tax = calculate_tax(order_data["total"])
@@ -15,3 +16,4 @@
 def get_order_summary(order_id):
     order = get_order(order_id)
+    log("getting order")
"""


def test_parse_basic_diff():
    files = parse_diff(SAMPLE_DIFF)
    assert len(files) == 1
    f = files[0]
    assert f.path == "utils.py"
    assert f.status == "modified"
    assert len(f.hunks) == 1
    assert f.hunks[0].start_line == 1


def test_parse_new_file():
    files = parse_diff(SAMPLE_DIFF_NEW_FILE)
    assert len(files) == 1
    assert files[0].status == "added"
    assert files[0].path == "new_module.py"


def test_parse_deleted_file():
    files = parse_diff(SAMPLE_DIFF_DELETED)
    assert len(files) == 1
    assert files[0].status == "deleted"


def test_parse_rename():
    files = parse_diff(SAMPLE_DIFF_RENAME)
    assert len(files) == 1
    f = files[0]
    assert f.status == "renamed"
    assert f.path == "new_name.py"
    assert f.old_path == "old_name.py"


def test_parse_multi_hunk():
    files = parse_diff(SAMPLE_DIFF_MULTI_HUNK)
    assert len(files) == 1
    assert len(files[0].hunks) == 2
    assert files[0].hunks[0].start_line == 3
    assert files[0].hunks[1].start_line == 16


def test_hunk_overlap():
    h = ChangedHunk(start_line=5, end_line=10)
    # Overlapping cases
    assert h.overlaps(1, 5) is True
    assert h.overlaps(10, 15) is True
    assert h.overlaps(7, 8) is True
    assert h.overlaps(1, 20) is True
    # Non-overlapping
    assert h.overlaps(1, 4) is False
    assert h.overlaps(11, 15) is False


def test_parse_empty_diff():
    files = parse_diff("")
    assert files == []


def test_parse_multiple_files():
    multi = SAMPLE_DIFF + "\n" + SAMPLE_DIFF_NEW_FILE
    files = parse_diff(multi)
    assert len(files) == 2
    assert files[0].path == "utils.py"
    assert files[1].path == "new_module.py"
