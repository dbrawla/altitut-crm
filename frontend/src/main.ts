import { createApp } from 'vue'
import { createPinia } from 'pinia'
import Oruga from '@oruga-ui/oruga-next'
import { bulmaConfig } from '@oruga-ui/theme-bulma'
import App from './App.vue'
import router from './router'
// main.css first so the Oruga/Bulma theme wins on shared selectors (.table,
// .modal, body); the custom .sidebar-*/.btn/.card classes don't exist in Bulma.
import './assets/main.css'
import '@oruga-ui/theme-bulma/style.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
// Oruga (Vue 3 successor to Buefy) with the Bulma theme — restores the original
// listmonk look and its dropdowns/tables/selects. theme.css bundles full Bulma.
app.use(Oruga, bulmaConfig)

app.mount('#app')
