import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Generator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, EmailStr
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Uuid as UUIDColumn,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def get_db() -> Generator[Session, None, None]:
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


# ─── Auth config ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ─── Enums ────────────────────────────────────────────────────────────────────
class OrderStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    cancelled = "cancelled"


class PaymentMethod(str, Enum):
    cash = "cash"
    card = "card"
    bank_transfer = "bank_transfer"


class PaymentStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"


# ─── ORM Models ───────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), primary_key=True, default=lambda: uuid.uuid4())
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), primary_key=True, default=lambda: uuid.uuid4())
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    price: Mapped[float] = mapped_column(Float(precision=2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), primary_key=True, default=lambda: uuid.uuid4())
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), ForeignKey("users.id"), nullable=False)
    total: Mapped[float] = mapped_column(Float(precision=2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=OrderStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), primary_key=True, default=lambda: uuid.uuid4())
    order_id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float(precision=2), nullable=False)
    subtotal: Mapped[float] = mapped_column(Float(precision=2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), primary_key=True, default=lambda: uuid.uuid4())
    order_id: Mapped[uuid.UUID] = mapped_column(UUIDColumn(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float(precision=2), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


Base.metadata.create_all(bind=engine)


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateProductRequest(BaseModel):
    name: str
    price: float
    stock: int


class ProductResponse(BaseModel):
    id: uuid.UUID
    name: str
    price: float
    stock: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateOrderItemRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: float
    subtotal: float

    model_config = {"from_attributes": True}


class CreateOrderRequest(BaseModel):
    items: list[CreateOrderItemRequest]


class OrderResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    total: float
    status: str
    items: list[OrderItemResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreatePaymentRequest(BaseModel):
    order_id: uuid.UUID
    amount: float
    method: PaymentMethod


class PaymentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    amount: float
    method: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Auth helpers ─────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
        token: str = Depends(oauth2_scheme),
        db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")

        if not isinstance(sub, str) or not sub.strip():
            raise credentials_exception

        user_id = uuid.UUID(sub)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user: User | None = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    return user


# ─── Application ──────────────────────────────────────────────────────────────
app = FastAPI()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Excepción no manejada: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ocurrió un error inesperado. Por favor intenta de nuevo más tarde."},
    )


# ─── Auth routes ──────────────────────────────────────────────────────────────
@app.post("/auth/register", response_model=UserResponse, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="El correo ya está registrado")

    user = User(
        name=data.name,
        email=data.email,
        password=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=LoginResponse)
def login(
        form: OAuth2PasswordRequestForm = Depends(),
        db: Session = Depends(get_db),
):
    user: User | None = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
        )
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "Bearer"}


# ─── User routes ──────────────────────────────────────────────────────────────
@app.get("/users/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user


@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


# ─── Product routes ───────────────────────────────────────────────────────────
@app.post("/products", response_model=ProductResponse, status_code=201)
def create_product(
        data: CreateProductRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    if data.price <= 0:
        raise HTTPException(status_code=400, detail="El precio debe ser mayor que 0")
    if data.stock < 0:
        raise HTTPException(status_code=400, detail="El stock no puede ser negativo")

    product = Product(name=data.name, price=data.price, stock=data.stock)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/products", response_model=list[ProductResponse])
def list_products(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    return db.query(Product).all()


@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
        product_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    product: Product | None = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return product


# ─── Order routes ─────────────────────────────────────────────────────────────
@app.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(
        data: CreateOrderRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    if not data.items:
        raise HTTPException(status_code=400, detail="El pedido debe tener al menos un producto")

    total = 0.0
    resolved_items = []

    for item in data.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="La cantidad debe ser mayor que 0")

        product: Product | None = db.get(Product, item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Producto {item.product_id} no encontrado")
        if product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Stock insuficiente para '{product.name}' (disponible: {product.stock})",
            )

        subtotal = product.price * item.quantity
        total += subtotal
        resolved_items.append((product, item.quantity, product.price, subtotal))

    order = Order(
        user_id=current_user.id,
        total=round(total, 2),
        status=OrderStatus.pending,
    )
    db.add(order)
    db.flush()

    for product, quantity, unit_price, subtotal in resolved_items:
        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
            subtotal=round(subtotal, 2),
        )
        db.add(order_item)
        product.stock -= quantity

    db.commit()
    db.refresh(order)
    order.items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    return order


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(
        order_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    order: Order | None = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para ver este pedido")

    order.items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    return order


# ─── Payment routes ───────────────────────────────────────────────────────────
@app.post("/payments", response_model=PaymentResponse, status_code=201)
def process_payment(
        data: CreatePaymentRequest,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    order: Order | None = db.query(Order).filter(Order.id == data.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para pagar este pedido")

    if order.status != OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail=f"El pedido no está pendiente (estado actual: {order.status})",
        )

    if round(data.amount, 2) != round(order.total, 2):
        raise HTTPException(
            status_code=400,
            detail=f"El monto ({data.amount}) no coincide con el total del pedido ({order.total})",
        )

    if order.total > 1_000_000 and data.method != PaymentMethod.bank_transfer:
        raise HTTPException(
            status_code=400,
            detail="Pedidos mayores a $1.000.000 solo pueden pagarse por transferencia bancaria",
        )
    else:
        payment_status = PaymentStatus.approved

    payment = Payment(
        order_id=data.order_id,
        amount=data.amount,
        method=data.method,
        status=payment_status,
    )
    db.add(payment)

    if payment_status == PaymentStatus.approved:
        order.status = OrderStatus.paid

    db.commit()
    db.refresh(payment)
    return payment


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(
        payment_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No autorizado para ver este pago")
    return payment
