"""Tests for tree-sitter symbol extraction — JavaScript and TypeScript."""

from blast_radius.symbols import extract_functions


JS_SOURCE = '''\
function validateInput(data) {
    if (!data.name) {
        throw new Error('Name required');
    }
    return sanitize(data);
}

const processOrder = (order) => {
    validateInput(order);
    const tax = calculateTax(order.total);
    return { ...order, tax };
};

class OrderService {
    constructor(db) {
        this.db = db;
    }

    async createOrder(data) {
        validateInput(data);
        const order = processOrder(data);
        return this.db.save(order);
    }

    getOrder(id) {
        return this.db.find(id);
    }
}

function calculateTax(amount) {
    return Math.round(amount * 0.1 * 100) / 100;
}
'''

TS_SOURCE = '''\
interface OrderData {
    name: string;
    total: number;
}

function validateInput(data: OrderData): boolean {
    if (!data.name) {
        throw new Error('Name required');
    }
    return true;
}

const processOrder = async (order: OrderData): Promise<Order> => {
    validateInput(order);
    const tax = calculateTax(order.total);
    return { ...order, tax };
};

export class OrderService {
    private db: Database;

    constructor(db: Database) {
        this.db = db;
    }

    async createOrder(data: OrderData): Promise<Order> {
        validateInput(data);
        const order = await processOrder(data);
        return this.db.save(order);
    }

    getOrder(id: string): Order | null {
        return this.db.find(id);
    }
}

function calculateTax(amount: number): number {
    return Math.round(amount * 0.1 * 100) / 100;
}
'''


def _by_name(funcs):
    return {f.name: f for f in funcs}


# ---- JavaScript ----

class TestJavaScriptExtraction:

    def test_finds_function_declarations(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        assert "validateInput" in funcs
        assert "calculateTax" in funcs

    def test_finds_arrow_functions(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        assert "processOrder" in funcs

    def test_finds_class_methods(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        assert "constructor" in funcs
        assert "createOrder" in funcs
        assert "getOrder" in funcs

    def test_containing_class(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        assert funcs["createOrder"].containing_class == "OrderService"
        assert funcs["getOrder"].containing_class == "OrderService"
        assert funcs["validateInput"].containing_class is None

    def test_call_sites_in_function(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        calls = funcs["processOrder"].call_sites
        assert "validateInput" in calls
        assert "calculateTax" in calls

    def test_call_sites_in_method(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        calls = funcs["createOrder"].call_sites
        assert "validateInput" in calls
        assert "processOrder" in calls

    def test_line_ranges(self):
        funcs = _by_name(extract_functions(JS_SOURCE, "app.js", "javascript"))
        assert funcs["validateInput"].start_line == 1
        assert funcs["processOrder"].start_line == 8

    def test_empty_file(self):
        assert extract_functions("", "empty.js", "javascript") == []


# ---- TypeScript ----

class TestTypeScriptExtraction:

    def test_finds_typed_functions(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        assert "validateInput" in funcs
        assert "calculateTax" in funcs

    def test_finds_typed_arrow_functions(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        assert "processOrder" in funcs

    def test_finds_typed_class_methods(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        assert "createOrder" in funcs
        assert "getOrder" in funcs

    def test_containing_class_with_types(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        assert funcs["createOrder"].containing_class == "OrderService"
        assert funcs["validateInput"].containing_class is None

    def test_call_sites_with_types(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        calls = funcs["createOrder"].call_sites
        assert "validateInput" in calls
        assert "processOrder" in calls

    def test_arrow_function_call_sites(self):
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        calls = funcs["processOrder"].call_sites
        assert "validateInput" in calls
        assert "calculateTax" in calls

    def test_ignores_interfaces(self):
        """Interfaces should not be extracted as functions."""
        funcs = _by_name(extract_functions(TS_SOURCE, "app.ts", "typescript"))
        assert "OrderData" not in funcs


# ---- TSX ----

TSX_SOURCE = '''\
function Greeting({ name }: { name: string }) {
    return <div>Hello {formatName(name)}</div>;
}

const UserCard = ({ user }: Props) => {
    const display = formatUser(user);
    return <Greeting name={display} />;
};
'''


class TestTSXExtraction:

    def test_finds_component_function(self):
        funcs = _by_name(extract_functions(TSX_SOURCE, "app.tsx", "tsx"))
        assert "Greeting" in funcs

    def test_finds_component_arrow(self):
        funcs = _by_name(extract_functions(TSX_SOURCE, "app.tsx", "tsx"))
        assert "UserCard" in funcs

    def test_call_sites_in_jsx(self):
        funcs = _by_name(extract_functions(TSX_SOURCE, "app.tsx", "tsx"))
        calls = funcs["Greeting"].call_sites
        assert "formatName" in calls
