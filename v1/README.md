# Sistema de Gestión de Pedidos — V1 (Monolito Acoplado)

Este proyecto es la **primera versión** de un sistema de gestión de usuarios, productos, pedidos y pagos, construido intencionalmente como un **monolito acoplado**. Su propósito es educativo: ilustrar los problemas de acoplamiento y falta de separación de responsabilidades antes de refactorizar hacia una arquitectura modular.

## Estructura del proyecto

```
v1/
├── app.py          # Todo el sistema en un solo archivo
├── .env            # Variables de entorno
├── requirements.txt
└── database.db     # Se genera automáticamente al iniciar
```

> Toda la lógica — modelos ORM, schemas Pydantic, autenticación, reglas de negocio y rutas — vive en `app.py`. Esto es intencional y representa el problema que se debe resolver.

---

## Instalación y ejecución

### 1. Entrar a la carpeta del proyecto

Asumiendo que el repositorio ya está clonado, navega a la carpeta de esta versión:

```bash
cd v1
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

Contenido del `.env`:

```env
DATABASE_URL=sqlite:///./database.db
SECRET_KEY=cambia_esto_en_produccion
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

> `SECRET_KEY` debe ser una cadena larga y aleatoria en entornos reales.

### 5. Iniciar el servidor

```bash
uvicorn app:app --reload
```

La API estará disponible en `http://localhost:8000`.

La documentación interactiva (Swagger) estará en `http://localhost:8000/docs`.

---

## Flujo de uso

El sistema sigue este flujo de negocio:

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

Un pedido se compone de uno o más productos. El total se calcula automáticamente a partir de los ítems — no se envía manualmente.

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

Al crear el pedido, el stock de cada producto se descuenta automáticamente.

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

| Método | Ruta                     | Descripción                        | Auth |
|--------|--------------------------|------------------------------------|------|
| POST   | `/auth/register`         | Registrar nuevo usuario            | No   |
| POST   | `/auth/login`            | Iniciar sesión y obtener token     | No   |
| GET    | `/users/me`              | Ver perfil del usuario autenticado | Sí   |
| GET    | `/users/{user_id}`       | Ver usuario por ID                 | Sí   |
| POST   | `/products`              | Crear producto                     | Sí   |
| GET    | `/products`              | Listar todos los productos         | Sí   |
| GET    | `/products/{product_id}` | Ver producto por ID                | Sí   |
| POST   | `/orders`                | Crear pedido con múltiples ítems   | Sí   |
| GET    | `/orders/{order_id}`     | Ver pedido por ID                  | Sí   |
| POST   | `/payments`              | Procesar pago de un pedido         | Sí   |
| GET    | `/payments/{payment_id}` | Ver pago por ID                    | Sí   |

---

## Validaciones del flujo de pedidos

Al crear un pedido, el sistema valida:

1. El pedido debe tener al menos un ítem
2. La cantidad de cada ítem debe ser mayor que 0
3. Cada producto referenciado debe existir
4. Cada producto debe tener stock suficiente para la cantidad solicitada

El total del pedido se calcula sumando los subtotales de cada ítem. El precio unitario se registra al momento de la compra, por lo que cambios futuros en el precio del producto no afectan pedidos ya creados.

## Validaciones del flujo de pagos

Al procesar un pago, el sistema valida:

1. El pedido debe existir y pertenecer al usuario autenticado
2. El pedido debe estar en estado `pending`
3. El monto enviado debe coincidir exactamente con el total del pedido
4. El método de pago debe ser uno de los valores válidos
5. Pedidos con total mayor a $1.000.000 solo pueden pagarse por transferencia bancaria
6. Los pagos en efectivo son rechazados siempre, independientemente del monto

Si el pago es aprobado, el pedido cambia automáticamente a estado `paid`.

---

## Problemas arquitectónicos identificados

Esta versión fue construida intencionalmente con los siguientes problemas para su análisis:

### 1. Cero separación de responsabilidades

Todo el sistema vive en `app.py`: configuración de base de datos, modelos ORM, schemas de validación, lógica de autenticación, reglas de negocio y rutas HTTP conviven sin ninguna frontera lógica. Agregar o modificar cualquier funcionalidad implica navegar un único archivo que mezcla todas las capas y todos los dominios.

### 2. Acoplamiento entre dominios

El dominio de pedidos accede directamente al modelo `Product` para leer precios, validar stock y descontarlo. El dominio de pagos accede directamente al modelo `Order` para leer su estado y modificarlo. Ninguno de estos cruces ocurre a través de una interfaz o contrato definido — cada dominio simplemente conoce y manipula los internos del otro.

### 3. Lógica de negocio en los route handlers

Las reglas de negocio están mezcladas con el código HTTP dentro de las funciones de ruta. Validaciones como el descuento de stock, el cálculo del total, el cambio de estado del pedido y las reglas de aprobación del pago ocurren directamente en el handler, junto al código que construye y retorna la respuesta HTTP.

### 4. Reglas de pago hardcodeadas

Las reglas que determinan si un pago es aprobado o rechazado están embebidas directamente dentro del endpoint, sin posibilidad de cambiarlas, extenderlas o reutilizarlas sin modificar el handler. Actualmente hay una regla activa: los pedidos mayores a $1.000.000 exigen transferencia bancaria como único método de pago válido.

### 5. Mutaciones cruzadas sin contrato

Cuando se crea un pedido, el handler de pedidos modifica directamente el stock de cada producto. Cuando se aprueba un pago, el handler de pagos modifica directamente el estado del pedido. Estas mutaciones cruzadas ocurren sin ningún mecanismo de coordinación, lo que hace imposible cambiar el comportamiento de un dominio sin revisar el código del otro.

### 6. Configuración acoplada al módulo

La creación del motor de base de datos y la configuración de autenticación ocurren al momento de importar el módulo. No existe ningún mecanismo de inyección que permita sustituir estos valores, lo que dificulta escribir pruebas unitarias o ejecutar el sistema en diferentes entornos sin modificar el código fuente.