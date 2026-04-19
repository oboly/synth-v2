# Capital Reservation v1

## Doel

Voorkomt overcommit van kapitaal.

---

## Flow

Plan creation:

- reserve amount
- available -= amount
- reserved += amount

Fill:

- reserved -= amount
- deployed += amount
- reservation → RELEASED

---

## States

- ACTIVE
- RELEASED

---

## Waarom

Zonder dit:

A + B + C kunnen tegelijk plannen terwijl er maar geld is voor 1.

