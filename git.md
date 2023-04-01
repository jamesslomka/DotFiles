
## Software configuration

### Git and Github Setup

#### Define your Git user

In your home directory:

`git config --global user.name "YOUR_NAME"`

`git config --global user.email "YOUR_SSENSE_EMAIL"`

Two factor authentication must be enabled under [settings/security](https://github.com/settings/security).

> IMPORTANT: After two-factor authentication is enabled, safely store your recovery codes in your password manager !

Go to: [settings/emails](https://github.com/settings/emails) and add your SSENSE email


#### SSH Config

> DISCLAIMER: A lot of the information below is similar to what you'll find on [GitHub Docs](https://docs.github.com/en/github/authenticating-to-github/connecting-to-github-with-ssh). 

To sign in on the CLI, you will need to create a one time key:

 Navigate to your home directory:

 `cd`

 Then, to create the key, replace `"YOUR_SSENSE_EMAIL"` with - yep, you guessed it - your SSENSE email.

`ssh-keygen -t rsa -b 4096 -C "YOUR_SSENSE_EMAIL"`

You can press enter for the next three prompts (using the default directory and empty passphrase)

`cd .ssh`

And copy the string inside the file: `id_rsa.pub`

Go to [settings/keys](https://github.com/settings/keys) and create a new SSH key, pasting the `id_rsa.pub` key in the body.

Click `Enable SSO`, next to the delete button on your newly created key, and authorize Groupe-Atallah.

#### Repository access validation

Choose a folder to save your Github repositories to (e.g. in your home folder, `mkdir Git`)

`cd Git`

Clone the [onboarding](https://github.com/Groupe-Atallah/onboarding) repository (make sure to copy the ssh link):

`git clone git@github.com:Groupe-Atallah/onboarding.git`

When prompted, enter your GitHub username.

When you are asked to enter a password, don't. Because of Two-Factor authentication, we will need to create a Personal Access Token. To accomplish this, nativate to [GitHub Settings/Tokens](https://github.com/settings/tokens) and click `Generate new token`

Give your token a name, and under scope, check off `repo` and `gist`

Copy that token and save it in a safe place. 

For that new token, also select Enable SSO and authorize `Groupe-Atallah`.

Go back to your terminal, which should still be prompting you for your password. Paste that token.

#### Add SSH key to known hosts

Enter `ssh -T git@github.com`. When Prompted, enter `yes`. You should now be authenticated.