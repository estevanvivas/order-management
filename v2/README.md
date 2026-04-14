# Sistema de Gestión de Pedidos — V2 (Arquitectura Modular)

Esta es la segunda versión del sistema de gestión de usuarios, productos, pedidos y pagos. Parte de la V1 (monolito acoplado) y la refactoriza hacia una **arquitectura modular**, donde cada dominio tiene responsabilidades claras, interfaces definidas y dependencias explícitas entre módulos.

---

## Estructura del proyecto

```
v2/
├── app/
│   ├── core/
│   │   ├── database.py       # Configuración del motor SQLAlchemy y sesión
│   │   └── security.py       # Hashing, verificación de contraseñas y JWT
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── models.py     # Modelo ORM: User
│   │   │   ├── schemas.py    # Schemas Pydantic: RegisterRequest, LoginResponse, UserResponse
│   │   │   ├── service.py    # get_current_user (dependencia de autenticación)
│   │   │   └── router.py     # Rutas: /auth/register, /auth/login, /users/me, /users/{id}
│   │   ├── products/
│   │   │   ├── models.py     # Modelo ORM: Product
│   │   │   ├── schemas.py    # Schemas Pydantic: CreateProductRequest, ProductResponse
│   │   │   ├── service.py    # reserve_stock (contrato expuesto hacia Orders)
│   │   │   └── router.py     # Rutas: /products
│   │   ├── orders/
│   │   │   ├── models.py     # Modelos ORM: Order, OrderItem
│   │   │   ├── schemas.py    # Schemas Pydantic + enum OrderStatus
│   │   │   ├── service.py    # get_order_by_id, mark_order_as_paid (contratos hacia Payments)
│   │   │   └── router.py     # Rutas: /orders
│   │   └── payments/
│   │       ├── models.py     # Modelo ORM: Payment
│   │       ├── schemas.py    # Schemas Pydantic + enums PaymentMethod, PaymentStatus
│   │       └── router.py     # Rutas: /payments
└── main.py                   # Punto de entrada: registra routers y crea tablas
```

Cada módulo es responsable únicamente de su dominio. La comunicación entre módulos ocurre exclusivamente a través de funciones de servicio definidas en `service.py`, nunca accediendo directamente a los modelos de otro módulo.

---

## Instalación y ejecución

### 1. Entrar a la carpeta del proyecto

```bash
cd v2
```

### 2. Crear y activar un entorno virtual

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

Crea un archivo `.env` en la raíz de `v2/` con el siguiente contenido:

```
DATABASE_URL=sqlite:///./database.db
SECRET_KEY=cambia_esto_en_produccion
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

> `SECRET_KEY` debe ser una cadena larga y aleatoria en entornos reales.

### 5. Iniciar el servidor

```bash
uvicorn app.main:app --reload
```

- API disponible en: `http://localhost:8000`
- Documentación interactiva (Swagger): `http://localhost:8000/docs`

---

## Flujo de uso

El sistema sigue el mismo flujo de negocio que la V1:

```
1. Registrar usuario  →  POST /auth/register
2. Iniciar sesión     →  POST /auth/login      (obtiene token JWT)
3. Crear productos    →  POST /products        (requiere token)
4. Crear pedido       →  POST /orders          (requiere token)
5. Procesar pago      →  POST /payments        (requiere token)
```

### Paso 1 — Registrar un usuario

```http
POST /auth/register
Content-Type: application/json

{
    "name": "John Doe",
    "email": "john@example.com",
    "password": "MiPassword123"
}
```

### Paso 2 — Iniciar sesión

```http
POST /auth/login
Content-Type: application/x-www-form-urlencoded

username=john@example.com&password=MiPassword123
```

Respuesta:

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer"
}
```

> A partir de aquí todos los endpoints requieren el header `Authorization: Bearer <token>`.

### Paso 3 — Crear un producto

```http
POST /products
Authorization: Bearer <token>
Content-Type: application/json

{
    "name": "Laptop Dell XPS 15",
    "price": 2500000.00,
    "stock": 10
}
```

### Paso 4 — Crear un pedido

Un pedido se compone de uno o más productos. El total se calcula automáticamente — no se envía manualmente.

```http
POST /orders
Authorization: Bearer <token>
Content-Type: application/json

{
    "items": [
        { "product_id": "uuid-del-producto", "quantity": 1 },
        { "product_id": "uuid-de-otro-producto", "quantity": 2 }
    ]
}
```

Al crear el pedido, el stock de cada producto se descuenta automáticamente mediante el contrato `reserve_stock` del módulo de productos.

### Paso 5 — Procesar un pago

```http
POST /payments
Authorization: Bearer <token>
Content-Type: application/json

{
    "order_id": "uuid-del-pedido",
    "amount": 2500000.00,
    "method": "bank_transfer"
}
```

Métodos de pago válidos: `card`, `bank_transfer`, `cash`.

---

## Endpoints disponibles

| Método | Ruta | Descripción | Auth |
|--------|------|-------------|------|
| POST | `/auth/register` | Registrar nuevo usuario | No |
| POST | `/auth/login` | Iniciar sesión y obtener token | No |
| GET | `/users/me` | Ver perfil del usuario autenticado | Sí |
| GET | `/users/{user_id}` | Ver usuario por ID | Sí |
| POST | `/products` | Crear producto | Sí |
| GET | `/products` | Listar todos los productos | Sí |
| GET | `/products/{product_id}` | Ver producto por ID | Sí |
| POST | `/orders` | Crear pedido con múltiples ítems | Sí |
| GET | `/orders/{order_id}` | Ver pedido por ID | Sí |
| POST | `/payments` | Procesar pago de un pedido | Sí |
| GET | `/payments/{payment_id}` | Ver pago por ID | Sí |

---

## Validaciones del flujo de pedidos

Al crear un pedido, el sistema valida:

- El pedido debe tener al menos un ítem
- La cantidad de cada ítem debe ser mayor que 0
- Cada producto referenciado debe existir
- Cada producto debe tener stock suficiente para la cantidad solicitada

El total se calcula sumando los subtotales de cada ítem. El precio unitario se registra al momento de la compra, por lo que cambios futuros en el precio del producto no afectan pedidos ya creados.

El descuento de stock ocurre a través de `reserve_stock` en `products/service.py`, que es el único punto donde se permite modificar el inventario de un producto desde fuera del módulo de productos.

---

## Validaciones del flujo de pagos

Al procesar un pago, el sistema valida:

- El pedido debe existir y pertenecer al usuario autenticado
- El pedido debe estar en estado `pending`
- El monto enviado debe coincidir exactamente con el total del pedido
- El método de pago debe ser uno de los valores válidos
- Pedidos con total mayor a `$1.000.000` solo pueden pagarse por transferencia bancaria

Si el pago es aprobado, el módulo de pagos invoca `mark_order_as_paid` del módulo de órdenes para actualizar el estado del pedido a `paid`, sin acceder directamente a su modelo.

---

## Diferencias respecto a la V1

| Aspecto | V1 (Monolito acoplado) | V2 (Monolito modular) |
|---|---|---|
| Organización | Todo en `app.py` | Separado por módulos con capas internas |
| Separación de responsabilidades | Ninguna | Cada módulo gestiona su propio dominio |
| Comunicación entre módulos | Acceso directo a modelos ajenos | A través de contratos en `service.py` |
| Lógica de negocio | Mezclada en los route handlers | Extraída a servicios |
| Testabilidad | Muy difícil | Cada módulo puede probarse de forma aislada |
| Escalabilidad del equipo | Un solo archivo genera conflictos | Módulos independientes permiten trabajo en paralelo |

---

## Contratos entre módulos

La V2 define interfaces explícitas que reemplazan el acceso directo entre dominios:

- **`products/service.py` → `reserve_stock(db, product_id, quantity)`**
  Usado por el módulo de Orders para validar stock y descontarlo. Es el único punto de entrada al dominio de Products desde el exterior.

- **`orders/service.py` → `get_order_by_id(db, order_id)`**
  Usado por el módulo de Payments para consultar un pedido sin acceder directamente al modelo `Order`.

- **`orders/service.py` → `mark_order_as_paid(db, order)`**
  Usado por el módulo de Payments para cambiar el estado del pedido tras un pago aprobado.

---

## Pregunta de reflexión

> **¿La solución realmente reduce el acoplamiento o solo reorganiza el código?**

La V2 reduce el acoplamiento de forma real en tanto que ningún módulo importa ni manipula directamente los modelos ORM de otro. Las dependencias cruzadas están canalizadas por funciones de servicio con contratos explícitos, lo que significa que el comportamiento interno de un módulo puede cambiar sin que los demás se vean afectados, siempre que el contrato se mantenga.

Sin embargo, sigue existiendo **acoplamiento temporal** (los módulos comparten la misma sesión de base de datos y transacción) y **acoplamiento de despliegue** (todo se despliega junto). Esto es inherente a la naturaleza de un monolito y no representa un defecto de diseño, sino una decisión consciente que prioriza la simplicidad operacional sobre la independencia total de despliegue.
