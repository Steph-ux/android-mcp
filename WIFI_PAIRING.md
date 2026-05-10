# Guide : Connexion WiFi ADB sans câble USB (Android 11+)

Android 11+ introduit le **débogage sans fil** (Wireless Debugging) qui permet
de connecter un téléphone via WiFi sans jamais avoir branché de câble USB.

---

## Méthode 1 — Wireless Debugging (Android 11+, recommandée)

### Sur le téléphone

1. **Paramètres** → **Options pour développeurs** → **Débogage sans fil**
   *(activer le débogage sans fil)*

2. Appuyer sur **"Associer l'appareil avec un code QR"** ou **"Associer avec un code de couplage"**

3. Note l'**adresse IP** affichée (ex: `192.168.1.42`) et le **port de couplage** (ex: `38765`)

### Sur le PC

```powershell
# Copier/coller l'IP:port et le code de couplage affiché sur le téléphone
adb pair 192.168.1.42:38765
# → Entrer le code à 6 chiffres affiché sur le téléphone

# Ensuite se connecter (port différent, affiché sous l'IP dans "Débogage sans fil")
adb connect 192.168.1.42:5555
# → "connected to 192.168.1.42:5555"
```

### Vérification

```powershell
adb devices
# → 192.168.1.42:5555    device
```

### Via android-mcp

```python
android_device(action="connect", params={"host": "192.168.1.42", "port": 5555})
```

---

## Méthode 2 — tcpip classique (Android 10 et antérieur, nécessite USB une fois)

```powershell
# 1. Brancher le câble USB une seule fois
adb tcpip 5555

# 2. Débrancher le câble
# 3. Se connecter via WiFi
adb connect 192.168.1.42:5555
```

---

## Méthode 3 — Android Debug Bridge over WiFi (app Play Store)

Des apps comme **"ADB WiFi"** (Play Store) permettent d'activer ADB WiFi
directement depuis le téléphone (si rooté ou avec accès débogage USB).

---

## Rendre la connexion persistante

La connexion WiFi ADB est perdue au redémarrage du téléphone.
Pour reconnecter automatiquement au démarrage de l'agent :

```python
# Dans ton script de démarrage
from device_manager import get_manager

dm = get_manager()
devices = dm.list_devices()
if not devices:
    dm.connect_wifi_adb("192.168.1.42", 5555)
    dm.select_device("192.168.1.42:5555")
```

Ou via MCP :
```
android_device(action="connect", params={"host": "192.168.1.42", "port": 5555})
android_device(action="select", params={"serial": "192.168.1.42:5555"})
```

---

## Portée réseau

- Le PC et le téléphone **doivent être sur le même réseau WiFi**
- Fonctionne via hotspot mobile (PC connecté au hotspot du téléphone)
- Ne fonctionne **pas** via VPN ou réseaux séparés (ex: 2.4GHz vs 5GHz sur certains routeurs)

---

## Troubleshooting

| Problème | Solution |
|----------|----------|
| `Connection refused` | Vérifier que le débogage sans fil est activé |
| `adb: device offline` | `adb disconnect` puis `adb connect` à nouveau |
| Code QR non scannable | Utiliser "Associer avec code" à la place |
| Port inconnu | Chercher dans Paramètres → Options développeurs → Débogage sans fil → Port |
| Lenteur > 200ms | Utiliser USB (câble) pour moins de latence |
