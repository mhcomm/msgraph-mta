# msgraph-mta
A simple mta sending mails via MSGraph

## Security

### Config file

The config file (default `~/.config/msgmta.json`) contains the client secret
of the application. `msgmta` refuses to read it if others can read or write
it:

    chmod 600 ~/.config/msgmta.json    # or 640 if shared with a group

### Restrict the application to the sender mailbox

`msgmta` requires the application permission `Mail.Send`. Without further
restriction this permission allows the application to send mails as **any**
mailbox of the tenant and not only as the configured `sender`.
Whoever obtains the client secret could therefore send mails in the name
of any user.

It is strongly recommended to limit the application to the mailbox(es) it
has to send from. This has to be done by an Exchange Online administrator
and cannot be done by `msgmta` itself. Microsoft documents two ways:

- [Role Based Access Control for Applications in Exchange Online](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac)
  (the current mechanism)
- [Application access policies](https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access)
  (the older mechanism), for example:

      New-ApplicationAccessPolicy -AppId <application_id> `
          -PolicyScopeGroupId <mail enabled security group containing the sender> `
          -AccessRight RestrictAccess `
          -Description "restrict msgmta to its sender mailbox"

      # check the result
      Test-ApplicationAccessPolicy -Identity <any other mailbox> -AppId <application_id>
