from dataclasses import dataclass
from typing import Optional


@dataclass
class SelfAssertedResponse:
    status: Optional[str]
    errorCode: Optional[str]
    message: Optional[str]


@dataclass
class Locale:
    lang: Optional[str]


@dataclass
class XhrSettings:
    retryEnabled: Optional[bool]
    retryMaxAttempts: Optional[int]
    retryDelay: Optional[int]
    retryExponent: Optional[int]
    retryOn: Optional[list[str]]


@dataclass
class SignInConfig:
    remoteResource: Optional[str]
    retryLimit: Optional[int]
    trimSpacesInPassword: Optional[bool]
    api: Optional[str]
    csrf: Optional[str]
    transId: Optional[str]
    pageViewId: Optional[str]
    suppressElementCss: Optional[bool]
    isPageViewIdSentWithHeader: Optional[bool]
    allowAutoFocusOnPasswordField: Optional[bool]
    pageMode: Optional[int]
    config: dict[str, Optional[str]]
    hosts: dict[str, Optional[str]]
    locale: Optional[Locale]
    xhrSettings: Optional[XhrSettings]


@dataclass
class ApparatusProperty:
    name: Optional[str]
    value: Optional[str]
    type: Optional[str]


@dataclass
class ApparatusAttribute:
    name: Optional[str]
    value: Optional[str]
    type: Optional[int]


@dataclass
class ApparatusInfo:
    apparatusId: Optional[int]
    apparatusName: Optional[str]
    productType: Optional[str]
    description: Optional[str]
    properties: Optional[list[ApparatusProperty]]
    attributes: Optional[list[ApparatusAttribute]]


@dataclass
class Weather:
    @dataclass
    class Temperature:
        value: Optional[float]
        unit: Optional[str]
        unitType: Optional[int]

    temperature: Optional[Temperature]
    iconCode: Optional[int]


@dataclass()
class Apparatus:
    apparatusId: Optional[int] = None
    serialNumber: Optional[str] = None
    name: Optional[str] = None
    type: Optional[int] = None
    localizedAddress: Optional[str] = None
    materialDescription: Optional[str] = None
    heroImageUrl: Optional[str] = None
    apparatusStatus: Optional[int] = None
    isConnected: Optional[bool] = None
    isConnecting: Optional[bool] = None
    showWarning: Optional[bool] = None
    weather: Optional[Weather] = None
    preferredDealerName: Optional[str] = None
    preferredDealerPhone: Optional[str] = None
    preferredDealerEmail: Optional[str] = None
    isDealerManaged: Optional[bool] = None
    isDealerUnmonitored: Optional[bool] = None
    modelNumber: Optional[str] = None
    panelId: Optional[str] = None

    @dataclass
    class Property:
        name: Optional[str]

        @dataclass
        class Value:
            type: Optional[int]
            status: Optional[int] | Optional[str]
            isLegacy: Optional[bool]
            isRunning: Optional[bool]
            deviceId: Optional[str]
            deviceType: Optional[str]
            signalStrength: Optional[str]
            batteryLevel: Optional[str]

        value: Optional[Value | list | str | int]
        type: Optional[int]

    properties: Optional[list[Property]] = None


@dataclass
class Address:
    """generated source for class Address"""

    line1: Optional[str]
    line2: Optional[str]
    city: Optional[str]
    region: Optional[str]
    country: Optional[str]
    postalCode: Optional[str]


@dataclass
class Subscription:
    """generated source for class Subscription"""

    type: Optional[int]
    status: Optional[int]
    isLegacy: Optional[bool]
    isDunning: Optional[bool]


@dataclass
class ApparatusDetail:
    @dataclass
    class Property:
        name: Optional[str]
        value: Optional[str | int | float | dict]
        type: Optional[int | str]

    @dataclass
    class ProductInfo:
        name: Optional[str]
        value: Optional[str]
        type: Optional[int]

    apparatusId: Optional[int] = None
    name: Optional[str] = None
    serialNumber: Optional[str] = None
    apparatusClassification: Optional[int] = None
    panelId: Optional[str] = None
    activationDate: Optional[str] = None
    deviceType: Optional[str] = None
    deviceSsid: Optional[str] = None
    shortDeviceId: Optional[str] = None
    apparatusStatus: Optional[int] = None
    heroImageUrl: Optional[str] = None
    statusLabel: Optional[str] = None
    statusText: Optional[str] = None
    eCodeLabel: Optional[str] = None
    weather: Optional[Weather] = None
    isConnected: Optional[bool] = None
    isConnecting: Optional[bool] = None
    showWarning: Optional[bool] = None
    hasMaintenanceAlert: Optional[bool] = None
    lastSeen: Optional[str] = None
    connectionTimestamp: Optional[str] = None
    address: Optional[Address] = None
    properties: Optional[list[Property]] = None
    tuProperties: Optional[list[Property]] = None
    subscription: Optional[Subscription] = None
    enrolledInVpp: Optional[bool] = None
    hasActiveVppEvent: Optional[bool] = None
    productInfo: Optional[list[Property]] = None
    hasDisconnectedNotificationsOn: Optional[bool] = None


@dataclass
class Item:
    apparatus: Apparatus
    apparatusDetail: ApparatusDetail
    empty: bool = False
