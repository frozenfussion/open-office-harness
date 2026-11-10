// SPDX-License-Identifier: AGPL-3.0-only
using System.Security.Cryptography;
using System.Text;

namespace ControlCentre.Platform;

public sealed class ModelKeys
{
  private readonly byte[] key;
  public ModelKeys(string? encoded)
  {
    try { key = Convert.FromBase64String(encoded ?? ""); }
    catch (FormatException) { throw new InvalidOperationException("CC_KEY_ENCRYPTION_KEY must contain 32 bytes encoded as base64"); }
    if (key.Length != 32) throw new InvalidOperationException("CC_KEY_ENCRYPTION_KEY must contain 32 bytes encoded as base64");
  }
  public string Encrypt(Guid id, string plaintext)
  {
    var nonce = RandomNumberGenerator.GetBytes(12);
    var data = Encoding.UTF8.GetBytes(plaintext);
    var ciphertext = new byte[data.Length]; var tag = new byte[16];
    using var aes = new AesGcm(key, 16);
    aes.Encrypt(nonce, data, ciphertext, tag, id.ToByteArray());
    return string.Join(':', "v1", Convert.ToBase64String(nonce), Convert.ToBase64String(ciphertext), Convert.ToBase64String(tag));
  }
  public string Decrypt(Guid id, string encrypted)
  {
    try
    {
      var parts = encrypted.Split(':');
      if (parts.Length != 4 || parts[0] != "v1") throw new CryptographicException();
      var data = Convert.FromBase64String(parts[2]); var plaintext = new byte[data.Length];
      using var aes = new AesGcm(key, 16);
      aes.Decrypt(Convert.FromBase64String(parts[1]), data, Convert.FromBase64String(parts[3]), plaintext, id.ToByteArray());
      return Encoding.UTF8.GetString(plaintext);
    }
    catch (Exception e) when (e is CryptographicException or FormatException or ArgumentException)
    { throw new ApiException(503, "unavailable", "Saved key could not be read; ask an admin to replace it"); }
  }
}
