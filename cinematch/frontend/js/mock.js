// ============================================================================
// CineMatch — mock.js
// A pretend backend that lives in the browser. Used when the site is opened
// with ?mock=1 (or MOCK_DEFAULT = true in config.js) so the UI can be built
// and demoed without FastAPI running.
//
// It answers every endpoint in CONTRACT.md section 5 with the same JSON shapes,
// keeps its little "database" in localStorage, and makes simple but believable
// recommendations from your ratings + the context you pick.
//
// Demo account: demo@cinematch.app / demo1234 (admin, already has ratings)
// Party friends: aman@example.com, riya@example.com
// Add &cold=1 to the URL to see the "waking up the server" screen.
// ============================================================================

import { seededRandom, timeOfDayFromHour } from "./utils.js";

// ---------------------------------------------------------------------------
// 1. Catalog — 64 titles. Posters are null on purpose (like the demo data),
//    so the frontend generates poster art for each one.
// Fields: id, title, year, type, genres, runtime, age, lang, critic, avg, count,
//         moods, start, end, arc, directors, cast, franchise, trailer, popularity,
//         seasons, overview
// ---------------------------------------------------------------------------
const RAW = [
  [1, "Toy Story", 1995, "m", "Adventure|Animation|Children|Comedy", 81, "U", "en", 96, 3.92, 57309, "feel-good|family|funny|heartwarming", "joy", "joy", "fall-rise", "John Lasseter", "Tom Hanks|Tim Allen|Don Rickles", "Toy Story Collection", "", 0.88, null, "A pull-string cowboy's place as favourite toy is threatened when a gleaming space ranger arrives on a boy's birthday."],
  [79132, "Inception", 2010, "m", "Action|Sci-Fi|Thriller|Mystery", 148, "UA 13+", "en", 87, 4.15, 49020, "mind-bending|thrilling|epic", "neutral", "surprise", "rise", "Christopher Nolan", "Leonardo DiCaprio|Joseph Gordon-Levitt|Elliot Page|Tom Hardy", "", "YoHD9XEInc0", 0.97, null, "A thief who steals secrets from inside dreams is offered one last job: plant an idea instead."],
  [109487, "Interstellar", 2014, "m", "Sci-Fi|Drama|Adventure", 169, "UA 13+", "en", 74, 4.08, 41000, "epic|mind-bending|melancholic|inspiring", "sadness", "joy", "fall-rise", "Christopher Nolan", "Matthew McConaughey|Anne Hathaway|Jessica Chastain", "", "zSWdZVtXT7E", 0.95, null, "With Earth's crops failing, a former pilot leads a crew through a wormhole to find humanity a new home."],
  [58559, "The Dark Knight", 2008, "m", "Action|Crime|Drama|Thriller", 152, "UA 13+", "en", 84, 4.18, 52000, "dark|thrilling|epic", "fear", "sadness", "fall", "Christopher Nolan", "Christian Bale|Heath Ledger|Aaron Eckhart", "The Dark Knight Collection", "EXeTwQWrcwY", 0.93, null, "Gotham's new protector faces an anarchist who wants to prove that anyone can be pushed into chaos."],
  [318, "The Shawshank Redemption", 1994, "m", "Crime|Drama", 142, "UA 16+", "en", 82, 4.41, 81482, "inspiring|slow-burn|heartwarming", "sadness", "joy", "rise", "Frank Darabont", "Tim Robbins|Morgan Freeman|Bob Gunton", "", "", 0.9, null, "Two prisoners build a friendship over decades inside a brutal penitentiary, holding on to hope."],
  [296, "Pulp Fiction", 1994, "m", "Crime|Thriller|Comedy", 154, "A", "en", 95, 4.19, 79672, "dark|funny|thrilling", "neutral", "surprise", "steady", "Quentin Tarantino", "John Travolta|Uma Thurman|Samuel L. Jackson", "", "", 0.86, null, "Hitmen, a boxer and a gangster's wife cross paths in a looping, darkly funny Los Angeles crime story."],
  [5618, "Spirited Away", 2001, "m", "Animation|Fantasy|Adventure|Children", 125, "U", "ja", 96, 4.23, 31000, "family|heartwarming|epic", "fear", "joy", "rise", "Hayao Miyazaki", "Rumi Hiiragi|Miyu Irino|Mari Natsuki", "", "", 0.84, null, "A girl trapped in a spirit world works in a bathhouse for the gods to free her parents."],
  [207830, "Parasite", 2019, "m", "Comedy|Drama|Thriller", 132, "A", "ko", 96, 4.21, 22000, "dark|thrilling|mind-bending", "joy", "fear", "rise-fall", "Bong Joon-ho", "Song Kang-ho|Lee Sun-kyun|Cho Yeo-jeong", "", "", 0.87, null, "A struggling family schemes its way into a wealthy household, until a secret below the floor surfaces."],
  [164909, "La La Land", 2016, "m", "Comedy|Drama|Romance|Musical", 128, "UA 7+", "en", 93, 3.96, 18000, "romantic|melancholic|feel-good", "joy", "sadness", "rise-fall", "Damien Chazelle", "Ryan Gosling|Emma Stone|John Legend", "", "", 0.82, null, "A jazz pianist and an aspiring actress fall in love while chasing their dreams in Los Angeles."],
  [109374, "The Grand Budapest Hotel", 2014, "m", "Comedy|Drama", 99, "UA 13+", "en", 88, 3.98, 21000, "funny|light|melancholic", "joy", "sadness", "rise-fall", "Wes Anderson", "Ralph Fiennes|Tony Revolori|Saoirse Ronan", "", "", 0.7, null, "A legendary concierge and his lobby boy are swept into a caper over a priceless painting."],
  [174055, "Get Out", 2017, "m", "Horror|Mystery|Thriller", 104, "A", "en", 85, 3.92, 15000, "scary|thrilling|dark|mind-bending", "neutral", "fear", "fall", "Jordan Peele", "Daniel Kaluuya|Allison Williams|Catherine Keener", "", "", 0.78, null, "A weekend visit to his girlfriend's parents turns into something far more sinister."],
  [187593, "Hereditary", 2018, "m", "Horror|Drama|Mystery", 127, "A", "en", 87, 3.71, 9000, "scary|dark|slow-burn", "sadness", "fear", "fall", "Ari Aster", "Toni Collette|Alex Wolff|Milly Shapiro", "", "", 0.62, null, "After a family matriarch dies, her daughter's household begins to unravel in terrifying ways."],
  [134130, "Mad Max: Fury Road", 2015, "m", "Action|Adventure|Sci-Fi", 120, "A", "en", 90, 3.95, 20000, "action-packed|thrilling|epic", "anger", "joy", "rise", "George Miller", "Tom Hardy|Charlize Theron|Nicholas Hoult", "Mad Max Collection", "", 0.79, null, "In a desert wasteland, a rebel driver and a drifter flee a warlord down a roaring war road."],
  [164179, "Arrival", 2016, "m", "Sci-Fi|Drama|Mystery", 116, "UA 7+", "en", 81, 3.97, 16000, "mind-bending|melancholic|slow-burn", "sadness", "surprise", "fall-rise", "Denis Villeneuve", "Amy Adams|Jeremy Renner|Forest Whitaker", "", "", 0.74, null, "A linguist races to understand alien visitors before global panic turns into war."],
  [176371, "Blade Runner 2049", 2017, "m", "Sci-Fi|Thriller|Drama", 164, "UA 16+", "en", 81, 3.93, 12000, "mind-bending|slow-burn|melancholic|dark", "neutral", "sadness", "steady", "Denis Villeneuve", "Ryan Gosling|Harrison Ford|Ana de Armas", "Blade Runner Collection", "", 0.71, null, "A replicant hunter uncovers a buried secret that could upend what is left of society."],
  [4973, "Amélie", 2001, "m", "Comedy|Romance", 122, "UA 13+", "fr", 69, 4.09, 26000, "feel-good|romantic|light|cozy", "neutral", "joy", "rise", "Jean-Pierre Jeunet", "Audrey Tautou|Mathieu Kassovitz|Rufus", "", "", 0.66, null, "A shy Parisian waitress quietly rearranges the lives of the people around her, then must risk her own happiness."],
  [215, "Before Sunrise", 1995, "m", "Drama|Romance", 101, "UA 13+", "en", 77, 4.02, 9000, "romantic|slow-burn|cozy", "neutral", "joy", "rise", "Richard Linklater", "Ethan Hawke|Julie Delpy", "Before Collection", "", 0.52, null, "Two strangers meet on a train and spend one long night walking and talking through Vienna."],
  [4993, "The Lord of the Rings: The Fellowship of the Ring", 2001, "m", "Adventure|Fantasy", 178, "UA 13+", "en", 92, 4.1, 57000, "epic|thrilling|inspiring", "joy", "fear", "fall", "Peter Jackson", "Elijah Wood|Ian McKellen|Viggo Mortensen", "The Lord of the Rings Collection", "", 0.9, null, "A humble hobbit sets out with eight companions to destroy a ring of terrible power."],
  [177765, "Coco", 2017, "m", "Animation|Children|Musical|Fantasy", 105, "U", "en", 81, 4.03, 11000, "heartwarming|family|feel-good", "sadness", "joy", "rise", "Lee Unkrich", "Anthony Gonzalez|Gael García Bernal|Benjamin Bratt", "", "", 0.76, null, "A boy who dreams of music crosses into the Land of the Dead to uncover his family's story."],
  [68954, "Up", 2009, "m", "Adventure|Animation|Children|Drama", 96, "U", "en", 88, 4.0, 27000, "heartwarming|family|funny|melancholic", "sadness", "joy", "fall-rise", "Pete Docter", "Ed Asner|Jordan Nagai|Christopher Plummer", "", "", 0.8, null, "A widowed balloon seller ties thousands of balloons to his house and floats toward South America."],
  [2571, "The Matrix", 1999, "m", "Action|Sci-Fi|Thriller", 136, "UA 16+", "en", 73, 4.16, 84545, "mind-bending|action-packed|thrilling", "fear", "joy", "rise", "Lana Wachowski|Lilly Wachowski", "Keanu Reeves|Laurence Fishburne|Carrie-Anne Moss", "The Matrix Collection", "", 0.92, null, "A hacker learns the world is a simulation and joins the fight against the machines that built it."],
  [1270, "Back to the Future", 1985, "m", "Adventure|Comedy|Sci-Fi", 116, "UA 7+", "en", 87, 4.02, 45000, "feel-good|funny|family|light", "surprise", "joy", "rise", "Robert Zemeckis", "Michael J. Fox|Christopher Lloyd|Lea Thompson", "Back to the Future Collection", "", 0.83, null, "A teenager accidentally travels to 1955 and has to make sure his parents fall in love."],
  [480, "Jurassic Park", 1993, "m", "Action|Adventure|Sci-Fi|Thriller", 127, "UA 13+", "en", 68, 3.7, 70000, "thrilling|epic|family", "surprise", "fear", "fall", "Steven Spielberg", "Sam Neill|Laura Dern|Jeff Goldblum", "Jurassic Park Collection", "", 0.85, null, "A theme park of cloned dinosaurs breaks down on its opening weekend."],
  [1721, "Titanic", 1997, "m", "Drama|Romance", 194, "UA 13+", "en", 75, 3.41, 55000, "romantic|epic|melancholic", "joy", "sadness", "rise-fall", "James Cameron", "Leonardo DiCaprio|Kate Winslet|Billy Zane", "", "", 0.84, null, "A penniless artist and a young aristocrat fall in love aboard a doomed ocean liner."],
  [858, "The Godfather", 1972, "m", "Crime|Drama", 175, "A", "en", 100, 4.32, 52498, "dark|slow-burn|epic", "joy", "fear", "fall", "Francis Ford Coppola", "Marlon Brando|Al Pacino|James Caan", "The Godfather Collection", "", 0.88, null, "The ageing head of a crime family hands his empire to his reluctant youngest son."],
  [1252, "Chinatown", 1974, "m", "Crime|Film-Noir|Mystery|Thriller", 130, "A", "en", 92, 4.12, 15000, "dark|slow-burn|mind-bending", "neutral", "sadness", "fall", "Roman Polanski", "Jack Nicholson|Faye Dunaway|John Huston", "", "", 0.45, null, "A private eye hired for a routine case is drawn into a web of water, power and family secrets."],
  [112552, "Whiplash", 2014, "m", "Drama|Musical", 107, "UA 16+", "en", 89, 4.08, 17000, "thrilling|inspiring|dark", "neutral", "surprise", "rise", "Damien Chazelle", "Miles Teller|J.K. Simmons|Paul Reiser", "", "", 0.73, null, "A young drummer is pushed to breaking point by a ruthless conservatory instructor."],
  [205383, "Knives Out", 2019, "m", "Comedy|Crime|Mystery", 130, "UA 13+", "en", 82, 3.96, 9000, "funny|mind-bending|cozy", "surprise", "joy", "rise", "Rian Johnson", "Daniel Craig|Ana de Armas|Chris Evans", "Knives Out Collection", "", 0.75, null, "A famed detective untangles the death of a wealthy crime novelist and his very suspicious family."],
  [179119, "Paddington 2", 2017, "m", "Adventure|Comedy|Children", 103, "U", "en", 88, 3.95, 4000, "feel-good|family|funny|heartwarming|cozy", "joy", "joy", "fall-rise", "Paul King", "Ben Whishaw|Hugh Grant|Sally Hawkins", "Paddington Collection", "", 0.6, null, "A polite bear is framed for stealing a pop-up book and lands in prison, where he wins everyone over."],
  [260000, "Everything Everywhere All at Once", 2022, "m", "Action|Comedy|Sci-Fi", 139, "UA 16+", "en", 90, 4.05, 8000, "mind-bending|funny|heartwarming|action-packed", "anger", "joy", "fall-rise", "Daniel Kwan|Daniel Scheinert", "Michelle Yeoh|Ke Huy Quan|Jamie Lee Curtis", "", "", 0.77, null, "A laundromat owner discovers she can borrow skills from her lives in other universes."],
  [240000, "Dune", 2021, "m", "Sci-Fi|Adventure|Drama", 155, "UA 13+", "en", 74, 3.92, 11000, "epic|slow-burn|thrilling", "neutral", "anger", "steady", "Denis Villeneuve", "Timothée Chalamet|Zendaya|Rebecca Ferguson", "Dune Collection", "", 0.86, null, "The heir of a noble house is thrust into a war over the most valuable planet in the universe."],
  [195000, "Free Solo", 2018, "m", "Documentary", 100, "U", "en", 83, 4.02, 2000, "inspiring|thrilling", "fear", "joy", "rise", "Jimmy Chin|Elizabeth Chai Vasarhelyi", "Alex Honnold|Tommy Caldwell", "", "", 0.4, null, "A climber prepares to scale El Capitan's 900-metre wall without a rope."],
  [1258, "The Shining", 1980, "m", "Horror|Thriller", 146, "A", "en", 66, 4.05, 35000, "scary|slow-burn|dark", "neutral", "fear", "fall", "Stanley Kubrick", "Jack Nicholson|Shelley Duvall|Danny Lloyd", "", "", 0.7, null, "A writer becomes the winter caretaker of an isolated hotel, and the hotel begins to take him over."],
  [48394, "Pan's Labyrinth", 2006, "m", "Fantasy|Drama|War", 118, "A", "es", 98, 4.0, 22000, "dark|melancholic|epic", "fear", "sadness", "fall", "Guillermo del Toro", "Ivana Baquero|Sergi López|Maribel Verdú", "", "", 0.55, null, "In post-war Spain, a girl escapes her cruel stepfather into a labyrinth of mythic tasks."],
  [2028, "Saving Private Ryan", 1998, "m", "Drama|War|Action", 169, "A", "en", 91, 4.05, 50000, "epic|thrilling|melancholic", "fear", "sadness", "steady", "Steven Spielberg", "Tom Hanks|Matt Damon|Tom Sizemore", "", "", 0.72, null, "After the Normandy landings, a squad is sent behind enemy lines to bring one soldier home."],
  [1201, "The Good, the Bad and the Ugly", 1966, "m", "Western|Action", 178, "UA 16+", "it", 90, 4.15, 17000, "epic|slow-burn|thrilling", "neutral", "surprise", "steady", "Sergio Leone", "Clint Eastwood|Eli Wallach|Lee Van Cleef", "The Dollars Trilogy", "", 0.5, null, "Three gunslingers race across the Civil War frontier toward a fortune in buried gold."],
  [170705, "Your Name", 2016, "m", "Animation|Romance|Fantasy|Drama", 106, "UA 7+", "ja", 79, 4.12, 7000, "romantic|mind-bending|heartwarming", "joy", "joy", "fall-rise", "Makoto Shinkai", "Ryunosuke Kamiki|Mone Kamishiraishi", "", "", 0.68, null, "Two teenagers in distant towns mysteriously start waking up in each other's bodies."],
  [7361, "Eternal Sunshine of the Spotless Mind", 2004, "m", "Drama|Romance|Sci-Fi", 108, "UA 13+", "en", 89, 4.07, 30000, "romantic|mind-bending|melancholic", "sadness", "joy", "fall-rise", "Michel Gondry", "Jim Carrey|Kate Winslet|Kirsten Dunst", "", "", 0.64, null, "After a painful break-up, a man has his ex erased from his memory, then fights to keep her."],
  [50872, "Ratatouille", 2007, "m", "Animation|Children|Comedy", 111, "U", "en", 96, 3.88, 22000, "feel-good|family|funny|cozy", "sadness", "joy", "rise", "Brad Bird", "Patton Oswalt|Lou Romano|Peter O'Toole", "", "", 0.74, null, "A rat with a gifted palate teams up with a clumsy kitchen boy to cook in Paris."],
  [116000, "Gone Girl", 2014, "m", "Drama|Thriller|Mystery", 149, "A", "en", 79, 3.9, 14000, "dark|mind-bending|thrilling|slow-burn", "sadness", "fear", "fall", "David Fincher", "Ben Affleck|Rosamund Pike|Neil Patrick Harris", "", "", 0.7, null, "When his wife vanishes on their anniversary, a husband becomes the centre of a media storm."],
  [27773, "Oldboy", 2003, "m", "Mystery|Thriller|Action", 120, "A", "ko", 77, 4.02, 13000, "dark|thrilling|mind-bending", "anger", "sadness", "fall", "Park Chan-wook", "Choi Min-sik|Yoo Ji-tae|Kang Hye-jung", "The Vengeance Trilogy", "", 0.58, null, "Imprisoned for fifteen years without explanation, a man is suddenly released and given five days to find out why."],
  [60397, "Mamma Mia!", 2008, "m", "Comedy|Musical|Romance", 108, "UA 7+", "en", 55, 3.2, 5000, "feel-good|light|funny|romantic", "joy", "joy", "steady", "Phyllida Lloyd", "Meryl Streep|Amanda Seyfried|Pierce Brosnan", "Mamma Mia! Collection", "", 0.58, null, "On a Greek island, a bride-to-be invites three men who might be her father to her wedding."],
  [72720, "3 Idiots", 2009, "m", "Comedy|Drama", 170, "UA 7+", "hi", 67, 4.13, 6000, "funny|inspiring|feel-good|heartwarming", "joy", "joy", "fall-rise", "Rajkumar Hirani", "Aamir Khan|R. Madhavan|Sharman Joshi|Kareena Kapoor", "", "", 0.8, null, "Two friends search for their long-lost college roommate, remembering how he upended the engineering rat race."],
  [168250, "Dangal", 2016, "m", "Drama|Action", 161, "U", "hi", 88, 4.08, 3500, "inspiring|family|heartwarming", "anger", "joy", "rise", "Nitesh Tiwari", "Aamir Khan|Fatima Sana Shaikh|Sanya Malhotra", "", "", 0.72, null, "A former wrestler trains his daughters to become world-class champions against every expectation."],
  [5034, "Lagaan", 2001, "m", "Drama|Musical|Adventure", 224, "U", "hi", 92, 3.98, 2500, "inspiring|epic|feel-good|family", "sadness", "joy", "rise", "Ashutosh Gowariker", "Aamir Khan|Gracy Singh|Rachel Shelley", "", "", 0.55, null, "Villagers crushed by a colonial tax wager everything on a cricket match against their rulers."],
  [88000, "Zindagi Na Milegi Dobara", 2011, "m", "Comedy|Drama|Adventure", 155, "UA 13+", "hi", 80, 3.97, 2200, "feel-good|light|inspiring|funny", "neutral", "joy", "rise", "Zoya Akhtar", "Hrithik Roshan|Farhan Akhtar|Abhay Deol|Katrina Kaif", "", "", 0.63, null, "Three old friends take a bachelor road trip through Spain and face what they have been avoiding."],
  [196000, "Andhadhun", 2018, "m", "Crime|Thriller|Comedy", 139, "UA 16+", "hi", 90, 4.06, 2800, "thrilling|dark|funny|mind-bending", "joy", "fear", "fall", "Sriram Raghavan", "Ayushmann Khurrana|Tabu|Radhika Apte", "", "", 0.66, null, "A pianist pretending to be blind accidentally witnesses a murder, and the lies multiply from there."],
  [112000, "Queen", 2014, "m", "Comedy|Drama", 146, "UA 13+", "hi", 86, 3.98, 1500, "feel-good|inspiring|funny|light", "sadness", "joy", "rise", "Vikas Bahl", "Kangana Ranaut|Lisa Haydon|Rajkummar Rao", "", "", 0.5, null, "Jilted a day before her wedding, a sheltered young woman goes on her honeymoon to Europe alone."],
  [137000, "Baahubali: The Beginning", 2015, "m", "Action|Fantasy|Adventure", 159, "UA 13+", "te", 75, 3.82, 2700, "epic|action-packed|thrilling", "surprise", "fear", "steady", "S. S. Rajamouli", "Prabhas|Rana Daggubati|Anushka Shetty|Tamannaah", "Baahubali Collection", "", 0.69, null, "A young man climbs a waterfall into a kingdom whose throne and history are bound to his own."],
  [270000, "RRR", 2022, "m", "Action|Drama|Adventure", 187, "UA 16+", "te", 87, 4.06, 3300, "epic|action-packed|thrilling|inspiring", "anger", "joy", "rise", "S. S. Rajamouli", "N. T. Rama Rao Jr.|Ram Charan|Alia Bhatt", "", "", 0.81, null, "Two revolutionaries on opposite sides of the Raj forge a friendship that could topple an empire."],
  [56000, "Taare Zameen Par", 2007, "m", "Drama|Children", 165, "U", "hi", 85, 4.17, 2500, "heartwarming|inspiring|family|melancholic", "sadness", "joy", "rise", "Aamir Khan", "Darsheel Safary|Aamir Khan|Tisca Chopra", "", "", 0.58, null, "An art teacher realises a struggling eight-year-old isn't lazy but dyslexic, and helps him shine."],
  [271000, "Kantara", 2022, "m", "Action|Drama|Thriller", 148, "UA 16+", "kn", 80, 3.95, 1200, "thrilling|epic|dark", "neutral", "surprise", "rise", "Rishab Shetty", "Rishab Shetty|Sapthami Gowda|Kishore", "", "", 0.6, null, "A coastal village's sacred rituals collide with a forest officer's land survey and old family feuds."],
  [6000, "Dilwale Dulhania Le Jayenge", 1995, "m", "Romance|Comedy|Drama|Musical", 189, "U", "hi", 84, 3.95, 2100, "romantic|feel-good|family|heartwarming", "joy", "joy", "fall-rise", "Aditya Chopra", "Shah Rukh Khan|Kajol|Amrish Puri", "", "", 0.62, null, "Two young Indians fall in love on a European trip, but her father has already promised her to someone else."],
  [203000, "Kumbalangi Nights", 2019, "m", "Drama|Comedy", 135, "UA 13+", "ml", 91, 4.05, 900, "heartwarming|slow-burn|funny|cozy", "sadness", "joy", "rise", "Madhu C. Narayanan", "Soubin Shahir|Shane Nigam|Fahadh Faasil", "", "", 0.35, null, "Four estranged brothers in a fishing village slowly learn how to be a family."],
  // ---- Series (movie_id = 10,000,000 + TMDB tv id) ----
  [10066732, "Stranger Things", 2016, "s", "Sci-Fi|Horror|Drama|Mystery", 50, "UA 16+", "en", 82, 4.1, 64, "thrilling|scary|epic", "fear", "joy", "fall-rise", "The Duffer Brothers", "Millie Bobby Brown|Winona Ryder|David Harbour", "", "", 0.94, 4, "When a boy vanishes in a small Indiana town, his friends uncover secret experiments and a terrifying other world."],
  [10001396, "Breaking Bad", 2008, "s", "Crime|Drama|Thriller", 47, "A", "en", 87, 4.4, 71, "dark|thrilling|slow-burn", "sadness", "fear", "fall", "Vince Gilligan", "Bryan Cranston|Aaron Paul|Anna Gunn", "", "", 0.9, 5, "A chemistry teacher with nothing to lose starts cooking meth, and slowly becomes someone else entirely."],
  [10070523, "Dark", 2017, "s", "Sci-Fi|Mystery|Thriller|Drama", 55, "UA 16+", "de", 85, 4.3, 38, "mind-bending|dark|slow-burn", "sadness", "neutral", "steady", "Baran bo Odar|Jantje Friese", "Louis Hofmann|Lisa Vicari|Oliver Masucci", "", "", 0.7, 3, "A missing child sets four families on a hunt through a small German town's tangled past and future."],
  [10101352, "Panchayat", 2020, "s", "Comedy|Drama", 35, "U", "hi", 88, 4.5, 55, "cozy|funny|heartwarming|light", "sadness", "joy", "rise", "Deepak Kumar Mishra", "Jitendra Kumar|Raghubir Yadav|Neena Gupta", "", "", 0.72, 3, "An engineering graduate takes a low-paid job as secretary of a remote village council and slowly finds his place."],
  [10002316, "The Office", 2005, "s", "Comedy", 22, "UA 7+", "en", 80, 4.3, 49, "funny|cozy|light|feel-good", "neutral", "joy", "steady", "Greg Daniels", "Steve Carell|Rainn Wilson|John Krasinski", "", "", 0.88, 9, "A documentary crew follows the gloriously awkward staff of a paper company's regional branch."],
  [10068595, "Planet Earth II", 2016, "s", "Documentary", 50, "U", "en", 96, 4.6, 27, "epic|inspiring|family", "surprise", "joy", "steady", "Elizabeth White", "David Attenborough", "", "", 0.55, 1, "Islands, jungles, deserts and cities: the planet's wildlife filmed closer than ever before."],
  [10091605, "Kota Factory", 2019, "s", "Drama|Comedy", 40, "UA 13+", "hi", 85, 4.4, 33, "inspiring|melancholic|funny", "sadness", "neutral", "steady", "Raghav Subbu", "Jitendra Kumar|Mayur More|Ranjan Raj", "", "", 0.6, 3, "A teenager navigates the pressure cooker of Kota's coaching factories with the help of a beloved teacher."],
  [10094605, "Arcane", 2021, "s", "Animation|Action|Fantasy|Sci-Fi", 40, "UA 16+", "en", 100, 4.6, 41, "epic|dark|action-packed", "anger", "sadness", "fall", "Christian Linke|Alex Yee", "Hailee Steinfeld|Ella Purnell|Kevin Alejandro", "", "", 0.83, 2, "Two sisters end up on opposite sides of a war between a gleaming city and its undercity."],
  [10019885, "Sherlock", 2010, "s", "Crime|Mystery|Drama", 88, "UA 13+", "en", 78, 4.4, 44, "mind-bending|thrilling|funny", "surprise", "surprise", "steady", "Mark Gatiss|Steven Moffat", "Benedict Cumberbatch|Martin Freeman|Una Stubbs", "", "", 0.76, 4, "A brilliant, impossible detective and an army doctor solve crimes in modern-day London."],
  [10097546, "Ted Lasso", 2020, "s", "Comedy|Drama", 35, "UA 13+", "en", 90, 4.4, 36, "feel-good|heartwarming|funny|inspiring", "neutral", "joy", "rise", "Bill Lawrence|Jason Sudeikis", "Jason Sudeikis|Hannah Waddingham|Brett Goldstein", "", "", 0.7, 3, "An American college football coach is hired to manage an English football club, knowing nothing about the sport."],
];

const split = (s) => (s ? s.split("|") : []);

const CATALOG = RAW.map((r, index) => {
  const [id, title, year, type, genres, runtime, age, lang, critic, avg, count, moods, start, end, arc,
    directors, cast, franchise, trailer, popularity, seasons, overview] = r;
  const rand = seededRandom(id * 7 + 3);
  const quality = 0.55 * (avg / 5) + 0.45 * (critic / 100);
  return {
    movie_id: id,
    title,
    year,
    content_type: type === "s" ? "series" : "movie",
    genres: split(genres),
    poster_url: null,
    backdrop_url: null,
    ml_mean: avg,
    ml_count: count,
    avg_rating: avg,
    rating_count: count,
    runtime,
    seasons,
    age_rating: age,
    language: lang,
    critic_score: critic,
    mood_tags: split(moods),
    start_emotion: start,
    end_emotion: end,
    emotion_arc: arc,
    overview,
    trailer_key: trailer || null,
    collection_name: franchise || null,
    directors: split(directors),
    cast: split(cast),
    keywords: [...split(moods), ...split(genres).map((g) => g.toLowerCase())],
    decade: Math.floor(year / 10) * 10,
    popularity_score: popularity,
    trending_velocity: Math.round((rand() * 0.8 - 0.2) * 100) / 100,
    quality_score: Math.round(quality * 100) / 100,
    imdb_rating: Math.round((avg * 2 - 0.2 + rand() * 0.4) * 10) / 10,
    order: index,
  };
});
const BY_ID = new Map(CATALOG.map((m) => [m.movie_id, m]));

// ---------------------------------------------------------------------------
// 2. Vocabulary (same strings as backend/app/vocab.py)
// ---------------------------------------------------------------------------
const AGE_ORDER = ["U", "UA 7+", "UA 13+", "UA 16+", "A"];
const LANG_NAMES = { en: "English", hi: "Hindi", ta: "Tamil", te: "Telugu", ml: "Malayalam", kn: "Kannada", ko: "Korean", ja: "Japanese", fr: "French", es: "Spanish", de: "German", it: "Italian" };
const WEATHER = [["sunny", "Sunny", "☀️"], ["cloudy", "Cloudy", "☁️"], ["rainy", "Rainy", "🌧️"], ["stormy", "Stormy", "⛈️"], ["snowy", "Snowy", "❄️"], ["foggy", "Foggy", "🌫️"], ["hot", "Hot", "🔥"], ["cold", "Cold", "🥶"]];
const OCCASIONS = [["date_night", "Date night", "💕"], ["family_night", "Family night", "👨‍👩‍👧"], ["friends_hangout", "Friends hangout", "🍕"], ["solo_chill", "Solo chill", "🛋️"], ["kids_time", "Kids time", "🧸"], ["late_night_thrills", "Late-night thrills", "🌙"], ["rainy_day_in", "Rainy day in", "☔"], ["weekend_binge", "Weekend binge", "📺"]];
const FESTIVALS = [
  ["navratri", "Navratri", "💃", "2026-10-11"], ["halloween", "Halloween", "🎃", "2026-10-31"], ["diwali", "Diwali", "🪔", "2026-11-08"],
  ["thanksgiving", "Thanksgiving", "🦃", "2026-11-26"], ["christmas", "Christmas", "🎄", "2026-12-25"], ["new_year", "New Year", "🎆", "2027-01-01"],
  ["pongal", "Pongal", "🍚", "2027-01-14"], ["valentines", "Valentine's Day", "💘", "2027-02-14"], ["eid", "Eid", "🌙", "2027-03-10"],
  ["holi", "Holi", "🎨", "2027-03-22"], ["independence_day", "Independence Day", "🇮🇳", "2027-08-15"], ["raksha_bandhan", "Raksha Bandhan", "🧵", "2027-08-17"],
  ["onam", "Onam", "🌼", "2027-09-12"],
];
const EMOTION_LABELS = { joy: "Happy", sadness: "Sad", fear: "Tense", anger: "Angry", surprise: "Surprised", disgust: "Disturbed", neutral: "Calm" };
const VALENCE = { joy: 1, surprise: 1, neutral: 0, sadness: -1, fear: -1, anger: -1, disgust: -1 };
const TIME_WORDS = { morning: "morning", afternoon: "afternoon", evening: "evening", night: "night", late_night: "late night" };

// moods that suit each piece of context
const WEATHER_MOODS = { rainy: ["cozy", "melancholic", "slow-burn", "romantic", "heartwarming"], sunny: ["feel-good", "light", "funny", "inspiring"], stormy: ["thrilling", "dark", "scary"], snowy: ["cozy", "heartwarming", "family"], foggy: ["mind-bending", "dark", "slow-burn"], hot: ["light", "funny", "action-packed"], cold: ["cozy", "heartwarming", "epic"], cloudy: ["melancholic", "slow-burn", "mind-bending"] };
const OCCASION_MOODS = { date_night: ["romantic", "feel-good", "light", "funny"], family_night: ["family", "heartwarming", "funny", "feel-good"], friends_hangout: ["funny", "action-packed", "thrilling"], solo_chill: ["slow-burn", "mind-bending", "melancholic", "cozy"], kids_time: ["family", "funny", "feel-good"], late_night_thrills: ["scary", "thrilling", "dark"], rainy_day_in: ["cozy", "heartwarming", "romantic"], weekend_binge: ["thrilling", "funny", "epic"] };
const FESTIVAL_MOODS = { diwali: ["family", "feel-good", "heartwarming"], navratri: ["family", "feel-good", "inspiring"], holi: ["funny", "feel-good", "light"], halloween: ["scary", "dark", "thrilling"], christmas: ["cozy", "family", "heartwarming"], new_year: ["feel-good", "inspiring", "funny"], valentines: ["romantic", "feel-good"], eid: ["family", "heartwarming"], raksha_bandhan: ["family", "heartwarming"], independence_day: ["inspiring", "epic"], onam: ["family", "feel-good"], pongal: ["family", "feel-good"], thanksgiving: ["family", "heartwarming", "cozy"] };
const TIME_MOODS = { morning: ["light", "feel-good"], afternoon: ["funny", "family"], evening: ["epic", "romantic"], night: ["thrilling", "mind-bending"], late_night: ["scary", "dark", "slow-burn"] };

// ---------------------------------------------------------------------------
// 3. The little database (localStorage)
// ---------------------------------------------------------------------------
const DB_KEY = "cinematch_mock_db_v2";
const DAY = 86400000;
const iso = (t) => new Date(t).toISOString();

function seedDb() {
  const now = Date.now();
  const users = [
    { id: "u-demo", email: "demo@cinematch.app", display_name: "Apoorva", password: "demo1234", is_admin: true, created_at: iso(now - 120 * DAY) },
    { id: "u-aman", email: "aman@example.com", display_name: "Aman", password: "aman1234", is_admin: false, created_at: iso(now - 90 * DAY) },
    { id: "u-riya", email: "riya@example.com", display_name: "Riya", password: "riya1234", is_admin: false, created_at: iso(now - 60 * DAY) },
  ];
  const rate = (pairs, base) => Object.fromEntries(pairs.map(([id, r], i) => [id, { rating: r, created_at: iso(base - i * 0.7 * DAY) }]));
  const ratings = {
    "u-demo": rate([[109487, 5], [79132, 4.5], [5618, 5], [72720, 5], [207830, 4.5], [164179, 4.5], [58559, 4], [164909, 4], [112552, 4], [174055, 3.5], [1721, 3], [60397, 2]], now - DAY),
    "u-aman": rate([[58559, 5], [134130, 4.5], [2571, 5], [270000, 4.5], [296, 4], [164909, 2.5], [60397, 1.5], [10001396, 5], [174055, 4]], now - 5 * DAY),
    "u-riya": rate([[164909, 5], [4973, 4.5], [215, 5], [72720, 4.5], [6000, 4.5], [174055, 2], [187593, 1.5], [10101352, 5], [5618, 4.5]], now - 4 * DAY),
  };
  const s = (movie_id, daysAgo, ratio, completed = false) => {
    const m = BY_ID.get(movie_id);
    const dur = m.runtime * 60;
    return {
      session_id: `s-${movie_id}-${daysAgo}`, user_id: "u-demo", movie_id, request_id: null,
      started_at: iso(now - daysAgo * DAY), ended_at: iso(now - daysAgo * DAY + dur * ratio * 1000),
      drop_off_sec: Math.round(dur * ratio), duration_sec: dur, completed, pause_count: 2, seek_back_count: 1,
      seek_forward_count: ratio < 0.5 ? 2 : 0, is_rewatch: false, start_number: 1,
    };
  };
  const sessions = [
    s(240000, 1, 0.62), s(10066732, 2, 0.3), s(10001396, 3, 0.45), s(196000, 4, 0.2), s(205383, 6, 0.74),
    s(109487, 9, 1, true), s(72720, 20, 1, true), { ...s(72720, 8, 1, true), session_id: "s-72720-r", is_rewatch: true, start_number: 2 },
  ];
  return { users, ratings, dismissals: {}, sessions, events: [], parties: {}, retrain: { status: "idle" }, model_version: "v20261002_103000" };
}

let db = loadDb();
function loadDb() {
  try {
    const saved = JSON.parse(localStorage.getItem(DB_KEY));
    if (saved && saved.users) return saved;
  } catch { /* fall through */ }
  return seedDb();
}
function save() {
  try { localStorage.setItem(DB_KEY, JSON.stringify(db)); } catch { /* full: keep in memory */ }
}

// ---------------------------------------------------------------------------
// 4. Helpers: users, cards, taste, scoring, reasons
// ---------------------------------------------------------------------------
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `id-${Math.random().toString(36).slice(2)}-${Date.now()}`);
const userById = (id) => db.users.find((u) => u.id === id);
const ratingsOf = (uid) => db.ratings[uid] || (db.ratings[uid] = {});
const dismissedOf = (uid) => db.dismissals[uid] || (db.dismissals[uid] = []);

function publicUser(u) {
  return { id: u.id, email: u.email, display_name: u.display_name, is_admin: !!u.is_admin, created_at: u.created_at, rating_count: Object.keys(ratingsOf(u.id)).length };
}

/** MovieCard shape (CONTRACT 5.2), with avg_rating merged with in-app ratings */
function card(m) {
  let sum = m.ml_mean * m.ml_count;
  let n = m.ml_count;
  for (const uid of Object.keys(db.ratings)) {
    const r = db.ratings[uid][m.movie_id];
    if (r) { sum += r.rating; n += 1; }
  }
  return {
    movie_id: m.movie_id, title: m.title, year: m.year, content_type: m.content_type, genres: m.genres,
    poster_url: m.poster_url, backdrop_url: m.backdrop_url,
    avg_rating: n ? Math.round((sum / n) * 100) / 100 : null, rating_count: n,
    runtime: m.runtime, age_rating: m.age_rating, language: m.language, critic_score: m.critic_score,
    mood_tags: m.mood_tags, start_emotion: m.start_emotion, end_emotion: m.end_emotion,
    overview: m.overview, trailer_key: m.trailer_key, collection_name: m.collection_name,
  };
}

const overlap = (a, b) => a.filter((x) => b.includes(x)).length;
const sigmoid = (x) => 1 / (1 + Math.exp(-x));
const stars = (r) => `${Number.isInteger(r) ? r : r.toFixed(1)}★`;

function similarity(a, b) {
  if (a.movie_id === b.movie_id) return -1;
  const g = overlap(a.genres, b.genres) / Math.max(1, Math.min(a.genres.length, b.genres.length));
  const md = overlap(a.mood_tags, b.mood_tags) / Math.max(1, Math.min(a.mood_tags.length, b.mood_tags.length));
  const people = overlap(a.directors, b.directors) * 0.35 + overlap(a.cast, b.cast) * 0.15;
  const era = 1 - Math.min(1, Math.abs(a.year - b.year) / 40);
  return 0.45 * g + 0.35 * md + people + 0.1 * era + (a.collection_name && a.collection_name === b.collection_name ? 0.4 : 0);
}

function tasteOf(uid) {
  const rated = ratingsOf(uid);
  const genres = {};
  const moods = {};
  const list = [];
  for (const [id, r] of Object.entries(rated)) {
    const m = BY_ID.get(Number(id));
    if (!m) continue;
    const w = r.rating - 3;
    m.genres.forEach((g) => { genres[g] = (genres[g] || 0) + w; });
    m.mood_tags.forEach((t) => { moods[t] = (moods[t] || 0) + w * 0.7; });
    list.push({ movie: m, rating: r.rating, created_at: r.created_at });
  }
  list.sort((a, b) => b.rating - a.rating || (b.created_at > a.created_at ? 1 : -1));
  return { genres, moods, list };
}

function personalScore(taste, m) {
  let g = 0;
  m.genres.forEach((x) => { g += taste.genres[x] || 0; });
  g /= Math.max(1, m.genres.length);
  let md = 0;
  m.mood_tags.forEach((x) => { md += taste.moods[x] || 0; });
  md /= Math.max(1, m.mood_tags.length);
  const quality = 0.5 * (m.critic_score / 100) + 0.5 * (m.avg_rating / 5);
  return 0.42 * quality + 0.33 * sigmoid(g / 1.6) + 0.2 * sigmoid(md / 1.6) + 0.05 * m.popularity_score;
}

/** Predicted stars for one user (used for watch-party member chips). */
function predictStars(uid, m) {
  const taste = tasteOf(uid);
  const s = personalScore(taste, m); // ~0.35–0.9
  return Math.max(0.5, Math.min(5, Math.round((1.2 + (s - 0.3) * 6.2) * 10) / 10));
}

function personalReason(taste, m) {
  let best = null;
  let bestSim = 0.55;
  for (const { movie, rating } of taste.list) {
    if (rating < 4) continue;
    const sim = similarity(movie, m);
    if (sim > bestSim) { best = { movie, rating }; bestSim = sim; }
  }
  if (best) return `Because you rated ${best.movie.title} ${stars(best.rating)}`;
  const g = [...m.genres].sort((a, b) => (taste.genres[b] || 0) - (taste.genres[a] || 0))[0];
  if (g && (taste.genres[g] || 0) > 1) return `Because you enjoy ${g === "Sci-Fi" ? "sci-fi" : g.toLowerCase()}`;
  if (m.critic_score >= 90) return `Critics score it ${m.critic_score}`;
  return "Popular with people who rate like you";
}

/** Turn a list of catalog movies into recommendation items. */
function asItems(list, taste, reasonFn) {
  return list.map(({ m, score }) => ({ ...card(m), score: Math.round(Math.min(0.99, score) * 100) / 100, reason: reasonFn ? reasonFn(m) : personalReason(taste, m) }));
}

function rankFor(uid, pool, extra = () => 0) {
  const taste = tasteOf(uid);
  return pool.map((m) => ({ m, score: personalScore(taste, m) + extra(m) })).sort((a, b) => b.score - a.score);
}

function basePool(uid, { includeRated = false } = {}) {
  const rated = ratingsOf(uid);
  const dismissed = new Set(dismissedOf(uid));
  return CATALOG.filter((m) => !dismissed.has(m.movie_id) && (includeRated || !rated[m.movie_id]));
}

// ---------------------------------------------------------------------------
// 5. Context + recommendations
// ---------------------------------------------------------------------------
function upcomingFestival() {
  const today = new Date(new Date().toDateString()).getTime();
  for (const [id, label, , date] of FESTIVALS) {
    const days = Math.round((new Date(date).getTime() - today) / DAY);
    if (days >= 0) return { id, label, date, days_away: days };
  }
  return null;
}

function contextResponse(query) {
  const hour = query.hour != null ? Number(query.hour) : new Date().getHours();
  const hasLoc = query.lat && query.lon;
  return {
    weather: hasLoc ? { id: "rainy", label: "Rainy", temp_c: 24.1, city: "Mathura", description: "light rain", source: "live" } : null,
    time_of_day: timeOfDayFromHour(hour),
    hour,
    upcoming_festival: upcomingFestival(),
    weather_status: hasLoc ? "live" : "no_location",
  };
}

function applyHardFilters(pool, ctx) {
  let list = pool;
  if (ctx.language) list = list.filter((m) => m.language === ctx.language);
  if (ctx.max_age_rating) list = list.filter((m) => AGE_ORDER.indexOf(m.age_rating) <= AGE_ORDER.indexOf(ctx.max_age_rating));
  if (ctx.content_type && ctx.content_type !== "any") list = list.filter((m) => m.content_type === ctx.content_type);
  if (ctx.genres?.length) list = list.filter((m) => overlap(m.genres, ctx.genres) > 0);
  if (ctx.time_available_min) list = list.filter((m) => m.runtime <= ctx.time_available_min);
  if (ctx.franchise_mode === "only") list = list.filter((m) => m.collection_name);
  if (ctx.franchise_mode === "exclude") list = list.filter((m) => !m.collection_name);
  if (ctx.directors?.length) list = list.filter((m) => overlap(m.directors, ctx.directors) > 0);
  if (ctx.actors?.length) list = list.filter((m) => overlap(m.cast, ctx.actors) > 0);
  if (ctx.occasion === "kids_time") list = list.filter((m) => AGE_ORDER.indexOf(m.age_rating) <= 1);
  if (ctx.occasion === "weekend_binge" && !ctx.content_type) list = list.filter((m) => m.content_type === "series" || m.runtime >= 140);
  if (ctx.nostalgia_decade) {
    const narrowed = list.filter((m) => m.decade === Number(ctx.nostalgia_decade));
    if (narrowed.length >= 4) list = narrowed;
  }
  return list;
}

function contextBoost(m, ctx, refs) {
  let b = 0;
  const why = [];
  const add = (v, text) => { b += v; if (text && v > 0) why.push([v, text]); };
  if (ctx.weather) add(0.05 * overlap(m.mood_tags, WEATHER_MOODS[ctx.weather] || []), `Perfect for a ${ctx.weather} ${TIME_WORDS[ctx.time_of_day] || "day"}`);
  if (ctx.time_of_day) add(0.025 * overlap(m.mood_tags, TIME_MOODS[ctx.time_of_day] || []), null);
  if (ctx.occasion) add(0.07 * overlap(m.mood_tags, OCCASION_MOODS[ctx.occasion] || []), `Great for ${OCCASIONS.find((o) => o[0] === ctx.occasion)?.[1].toLowerCase()}`);
  if (ctx.festival) add(0.06 * overlap(m.mood_tags, FESTIVAL_MOODS[ctx.festival] || []) + (["hi", "te", "ta", "ml", "kn"].includes(m.language) && ["diwali", "navratri", "holi", "onam", "pongal", "raksha_bandhan", "independence_day", "eid"].includes(ctx.festival) ? 0.08 : 0), `A ${FESTIVALS.find((f) => f[0] === ctx.festival)?.[1]} favourite`);
  if (ctx.start_emotion) add(m.start_emotion === ctx.start_emotion ? 0.09 : VALENCE[m.start_emotion] === VALENCE[ctx.start_emotion] ? 0.04 : 0, null);
  if (ctx.end_emotion) {
    const v = m.end_emotion === ctx.end_emotion ? 0.14 : VALENCE[m.end_emotion] === VALENCE[ctx.end_emotion] ? 0.06 : -0.05;
    add(v, ctx.start_emotion ? `Starts ${EMOTION_LABELS[m.start_emotion].toLowerCase()}, ends ${EMOTION_LABELS[m.end_emotion].toLowerCase()}, just as you asked` : `Leaves you feeling ${EMOTION_LABELS[m.end_emotion].toLowerCase()}`);
  }
  if (ctx.nostalgia_decade) add(m.decade === Number(ctx.nostalgia_decade) ? 0.12 : 0, `A trip back to the ${String(ctx.nostalgia_decade).slice(2)}s`);
  if (ctx.time_available_min) add(0.01, `Fits in your ${ctx.time_available_min >= 60 ? `${ctx.time_available_min / 60} hours` : `${ctx.time_available_min} minutes`}`.replace("1 hours", "hour").replace(".5 hours", "½ hours"));
  if (refs.length) {
    let best = null;
    let bestSim = 0;
    for (const r of refs) { const s = similarity(r, m); if (s > bestSim) { bestSim = s; best = r; } }
    add(bestSim * 0.35, best ? `Because you picked ${best.title}` : null);
  }
  if (ctx.directors?.length) add(0.05, `Directed by ${m.directors.find((d) => ctx.directors.includes(d)) || m.directors[0]}`);
  if (ctx.actors?.length) add(0.05, `Starring ${m.cast.find((a) => ctx.actors.includes(a)) || m.cast[0]}`);
  why.sort((a, b) => b[0] - a[0]);
  return { boost: b, reason: why[0]?.[1] || null };
}

function mixLabel(ctx) {
  const parts = [];
  const occ = OCCASIONS.find((o) => o[0] === ctx.occasion)?.[1];
  const fest = FESTIVALS.find((f) => f[0] === ctx.festival)?.[1];
  if (fest) parts.push(`${fest} picks`);
  else if (occ) parts.push(`${occ} picks`);
  else if (ctx.weather) parts.push(`For this ${ctx.weather} ${TIME_WORDS[ctx.time_of_day] || "day"}`);
  else if (ctx.nostalgia_decade) parts.push(`${String(ctx.nostalgia_decade).slice(2)}s nostalgia`);
  else if (ctx.genres?.length) parts.push(`${ctx.genres.slice(0, 2).join(" and ")} for you`);
  else parts.push("Your mix");
  if (ctx.start_emotion && ctx.end_emotion) parts.push(`from ${EMOTION_LABELS[ctx.start_emotion].toLowerCase()} to ${EMOTION_LABELS[ctx.end_emotion].toLowerCase()}`);
  else if (ctx.end_emotion) parts.push(`that end ${EMOTION_LABELS[ctx.end_emotion].toLowerCase()}`);
  return parts.join(", ").replace(/^./, (c) => c.toUpperCase());
}

function trending(pool, limit) {
  return [...pool].sort((a, b) => b.popularity_score * (1 + b.trending_velocity * 0.3) - a.popularity_score * (1 + a.trending_velocity * 0.3)).slice(0, limit);
}

function recommend(uid, ctx = {}, limit = 20) {
  const t0 = performance.now();
  const pool = basePool(uid);
  const taste = tasteOf(uid);
  const refs = (ctx.reference_movie_ids || []).map((id) => BY_ID.get(Number(id))).filter(Boolean);
  const refIds = new Set(refs.map((r) => r.movie_id));
  const filtered = applyHardFilters(pool, ctx).filter((m) => !refIds.has(m.movie_id));
  let items;
  let fallback = false;
  let label;
  if (filtered.length === 0) {
    // FR-4.4 / AC-3: never empty — popularity list, relaxing the filters
    fallback = true;
    label = "Trending now";
    const relaxed = applyHardFilters(pool, { max_age_rating: ctx.max_age_rating, content_type: ctx.content_type });
    items = trending(relaxed.length ? relaxed : pool, limit).map((m) => ({ ...card(m), score: Math.round(m.popularity_score * 100) / 100, reason: "Popular on CineMatch right now" }));
  } else {
    const ranked = filtered.map((m) => {
      const { boost, reason } = contextBoost(m, ctx, refs);
      return { m, score: personalScore(taste, m) + boost, reason };
    }).sort((a, b) => b.score - a.score).slice(0, Math.min(20, limit));
    items = ranked.map(({ m, score, reason }) => ({ ...card(m), score: Math.round(Math.min(0.99, score) * 100) / 100, reason: reason || personalReason(taste, m) }));
    label = mixLabel(ctx);
  }
  const request_id = uuid();
  logRequest(uid, "/api/recommendations", ctx, items, fallback, performance.now() - t0);
  return { request_id, label, fallback, items, context_used: ctx };
}

function logRequest(uid, endpoint, ctx, items, fallback, latency) {
  db.events.push({ kind: "request", user_id: uid, endpoint, context: ctx, n: items.length, fallback, latency_ms: latency, created_at: iso(Date.now()) });
  if (db.events.length > 600) db.events.splice(0, db.events.length - 600);
}

// ---------------------------------------------------------------------------
// 6. Home rows (CONTRACT 5.6 GET /api/home)
// ---------------------------------------------------------------------------
function home(uid, query) {
  const context = contextResponse(query);
  const taste = tasteOf(uid);
  const pool = basePool(uid);
  const rows = [];
  const push = (row, list) => { if (list.length >= 4) rows.push({ ...row, items: list.slice(0, 16) }); };
  const reasonWith = (text) => () => text;

  // Continue watching: sessions that stopped before 90%
  const seen = new Set();
  const cw = [];
  for (const s of [...db.sessions].filter((x) => x.user_id === uid).sort((a, b) => (a.started_at < b.started_at ? 1 : -1))) {
    if (seen.has(s.movie_id)) continue;
    seen.add(s.movie_id);
    if (!s.completed && s.duration_sec && s.drop_off_sec / s.duration_sec < 0.9) {
      const m = BY_ID.get(s.movie_id);
      if (m) cw.push({ ...card(m), score: 1, reason: `Pick up at ${Math.round((s.drop_off_sec / s.duration_sec) * 100)}%` });
    }
  }
  if (cw.length >= 4) rows.push({ id: "continue_watching", title: "Continue watching", subtitle: "Pick up where you left off", filter: {}, items: cw });

  const forYou = rankFor(uid, pool);
  push({ id: "for_you", title: "Recommended for you", subtitle: "Based on your ratings", filter: {} }, asItems(forYou.slice(0, 16), taste));

  const anchor = taste.list.find((x) => x.rating >= 4.5);
  if (anchor) {
    const sims = pool.map((m) => ({ m, score: 0.5 + similarity(anchor.movie, m) * 0.5 })).sort((a, b) => b.score - a.score).slice(0, 14);
    push({ id: `because_${anchor.movie.movie_id}`, title: `Because you rated ${anchor.movie.title}`, subtitle: `You gave it ${stars(anchor.rating)}`, filter: { reference_movie_ids: [anchor.movie.movie_id] } },
      asItems(sims, taste, reasonWith(`Because you rated ${anchor.movie.title} ${stars(anchor.rating)}`)));
  }

  if (context.weather) {
    const w = context.weather.id;
    const list = rankFor(uid, pool, (m) => 0.08 * overlap(m.mood_tags, WEATHER_MOODS[w] || [])).filter(({ m }) => overlap(m.mood_tags, WEATHER_MOODS[w] || []) > 0);
    push({ id: "weather", title: `Perfect for this ${w} ${TIME_WORDS[context.time_of_day]}`, subtitle: `${context.weather.city}, ${Math.round(context.weather.temp_c)}°`, filter: { weather: w, time_of_day: context.time_of_day } },
      asItems(list, taste, reasonWith(`Perfect for a ${w} ${TIME_WORDS[context.time_of_day]}`)));
  }

  const fit = rankFor(uid, pool.filter((m) => m.runtime <= 120));
  push({ id: "time_fit", title: "Fits in two hours", subtitle: "Done before it gets late", filter: { time_available_min: 120 } }, asItems(fit, taste, (m) => `Runs ${Math.floor(m.runtime / 60) ? `${Math.floor(m.runtime / 60)}h ` : ""}${m.runtime % 60}m`));

  const fest = context.upcoming_festival;
  if (fest && fest.days_away <= 21) {
    const moods = FESTIVAL_MOODS[fest.id] || [];
    const list = rankFor(uid, pool, (m) => 0.1 * overlap(m.mood_tags, moods) + (["hi", "te", "ml", "kn", "ta"].includes(m.language) ? 0.12 : 0)).filter(({ m }) => overlap(m.mood_tags, moods) > 0);
    push({ id: "festival", title: `${fest.label} nights`, subtitle: fest.days_away === 0 ? "Today" : `${fest.label} is ${fest.days_away} days away`, filter: { festival: fest.id } },
      asItems(list, taste, reasonWith(`A ${fest.label} favourite`)));
  }

  push({ id: "trending", title: "Trending now", subtitle: "What everyone is watching", filter: {} },
    trending(pool, 16).map((m) => ({ ...card(m), score: m.popularity_score, reason: m.trending_velocity > 0.25 ? "Climbing fast this week" : "Popular on CineMatch right now" })));

  push({ id: "acclaimed", title: "Critically acclaimed", subtitle: "Critics' highest scores", filter: {} },
    asItems(pool.filter((m) => m.critic_score >= 88).map((m) => ({ m, score: m.critic_score / 100 })).sort((a, b) => b.score - a.score), taste, (m) => `Critics score it ${m.critic_score}`));

  push({ id: "hidden_gems", title: "Hidden gems", subtitle: "Loved by few, rated highly", filter: {} },
    asItems(pool.filter((m) => m.popularity_score < 0.62 && m.quality_score > 0.8).map((m) => ({ m, score: m.quality_score })).sort((a, b) => b.score - a.score), taste, () => "Rated highly, seen by few"));

  push({ id: "feel_good", title: "Ends with a smile", subtitle: "Whatever the start, a happy ending", filter: { end_emotion: "joy" } },
    asItems(rankFor(uid, pool.filter((m) => m.end_emotion === "joy")), taste, (m) => `Starts ${EMOTION_LABELS[m.start_emotion].toLowerCase()}, ends happy`));

  push({ id: "nostalgia", title: "90s nostalgia", subtitle: "Straight from the VHS shelf", filter: { nostalgia_decade: 1990 } },
    asItems(rankFor(uid, pool.filter((m) => m.decade === 1990)), taste, (m) => `From ${m.year}`));

  push({ id: "series_binge", title: "Series to binge", subtitle: "One more episode, then sleep", filter: { content_type: "series" } },
    asItems(rankFor(uid, pool.filter((m) => m.content_type === "series")), taste));

  push({ id: "date_night", title: "Date night", subtitle: "Romance, laughs and a little sparkle", filter: { occasion: "date_night" } },
    asItems(rankFor(uid, pool.filter((m) => overlap(m.mood_tags, ["romantic", "feel-good"]) > 0 && m.age_rating !== "A")), taste, () => "Great for date night"));

  push({ id: "mind_bending", title: "Mind-bending", subtitle: "Films to argue about afterwards", filter: { genres: ["Sci-Fi", "Mystery"] } },
    asItems(rankFor(uid, pool.filter((m) => m.mood_tags.includes("mind-bending"))), taste));

  const heroPick = forYou[0]?.m || CATALOG[1];
  const request_id = uuid();
  logRequest(uid, "/api/home", { hour: context.hour, weather: context.weather?.id }, forYou.slice(0, 20), false, 40 + Math.random() * 60);
  return {
    request_id,
    context,
    needs_onboarding: Object.keys(ratingsOf(uid)).length < 5,
    hero: { ...card(heroPick), score: Math.round(Math.min(0.99, forYou[0]?.score || 0.9) * 100) / 100, reason: personalReason(taste, heroPick) },
    rows,
  };
}

// ---------------------------------------------------------------------------
// 7. Profile insights, admin stats
// ---------------------------------------------------------------------------
function insights(uid) {
  const taste = tasteOf(uid);
  const genreScores = Object.entries(taste.genres).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = genreScores[0]?.[1] || 1;
  const sessions = db.sessions.filter((s) => s.user_id === uid);
  const done = sessions.filter((s) => s.completed).length;
  const selects = db.events.filter((e) => e.user_id === uid && e.type === "select" && e.value);
  const decades = {};
  taste.list.filter((x) => x.rating >= 4).forEach(({ movie }) => { decades[movie.decade] = (decades[movie.decade] || 0) + 1; });
  const favDecade = Object.entries(decades).sort((a, b) => b[1] - a[1])[0]?.[0];
  const topMoods = Object.entries(taste.moods).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k]) => k);
  const g = genreScores.map(([k]) => (k === "Sci-Fi" ? "sci-fi" : k.toLowerCase()));
  return {
    top_genres: genreScores.map(([genre, v]) => ({ genre, score: Math.round((v / max) * 100) / 100 })),
    completion_rate: sessions.length ? done / sessions.length : 0,
    avg_browse_to_select_ms: selects.length ? selects.reduce((a, e) => a + e.value, 0) / selects.length : 41800,
    rewatch_count: sessions.filter((s) => s.is_rewatch).length,
    binge_score: 0.64,
    seek_forward_rate: sessions.length ? sessions.filter((s) => s.seek_forward_count > 0).length / sessions.length : 0,
    favourite_decade: favDecade ? Number(favDecade) : null,
    ratings_count: taste.list.length,
    sessions_count: sessions.length,
    taste_summary: taste.list.length
      ? `You love ${topMoods[0] || "big"} ${g[0] || "drama"} and ${topMoods[1] || "warm"} ${g[1] || "comedy"}, and you rarely abandon a film once it hooks you.`
      : "Rate a few films and we'll describe your taste here.",
  };
}

function adminStats() {
  const rand = seededRandom(42);
  const days = [...Array(30)].map((_, i) => new Date(Date.now() - (29 - i) * DAY).toISOString().slice(0, 10));
  const ratingsByDay = days.map((date, i) => ({ date, count: Math.round(18 + i * 1.6 + rand() * 22 + (i % 7 === 5 || i % 7 === 6 ? 14 : 0)) }));
  const requestsByDay = days.map((date, i) => ({ date, count: Math.round(120 + i * 6 + rand() * 70 + (i % 7 >= 5 ? 60 : 0)) }));
  const hist = { "0.5": 41, "1.0": 88, "1.5": 102, "2.0": 236, "2.5": 318, "3.0": 702, "3.5": 951, "4.0": 1288, "4.5": 806, "5.0": 694 };
  const allRatings = Object.values(db.ratings).reduce((a, r) => a + Object.keys(r).length, 0);
  const top = [...CATALOG].sort((a, b) => b.ml_mean - a.ml_mean).slice(0, 5).map((m) => ({ movie: card(m), avg: m.ml_mean, count: m.ml_count }));
  return {
    users: 1284 + db.users.length, ratings: 5226 + allRatings, sessions: 3410 + db.sessions.length, events: 48210 + db.events.length,
    requests: requestsByDay.reduce((a, d) => a + d.count, 0),
    ratings_by_day: ratingsByDay, rating_histogram: hist, top_rated: top,
    rec_ctr: 0.184, avg_browse_to_select_ms: 38600, avg_completion: 0.71, dismiss_rate: 0.037,
    latency_p50_ms: 182, latency_p95_ms: 640,
    requests_by_day: requestsByDay,
    context_usage: { time_of_day: 980, weather: 412, time_available_min: 288, genres: 305, occasion: 233, language: 210, content_type: 160, reference_movie_ids: 140, start_emotion: 120, end_emotion: 118, max_age_rating: 98, nostalgia_decade: 75, festival: 61, directors: 52, actors: 47, franchise_mode: 33 },
    model: {
      version: db.model_version, trained_at: "2026-10-02T10:30:00Z", algorithm: "SVD (Surprise, biased matrix factorisation)",
      n_factors: 100, n_epochs: 20, n_items: CATALOG.length, n_cf_items: 54, n_train_ratings: 100836, n_users_trained: 610,
      embedding_model: "all-MiniLM-L6-v2", dataset_mode: "sample",
      metrics: { rmse: 0.874, mae: 0.672, baseline_global_mean_rmse: 1.042, baseline_bias_rmse: 0.902, precision_at_10: 0.184, recall_at_10: 0.097, ndcg_at_10: 0.231 },
      blend_weights: { cf: 0.45, content: 0.15, ref: 0.35, ctx: 0.25, quality: 0.12, trend: 0.05, behavior: 0.1 },
      data_sources: ["MovieLens latest-small", "TMDB API", "IMDb non-commercial datasets"],
    },
  };
}

// ---------------------------------------------------------------------------
// 8. Router: (method, path) -> handler
// ---------------------------------------------------------------------------
const ok = (data, status = 200) => ({ status, data });
const fail = (status, detail) => ({ status, data: { detail } });
const noContent = () => ({ status: 204, data: null });

function requireUser(token) {
  if (!token || !token.startsWith("mock-")) return null;
  return userById(token.slice(5)) || null;
}

function catalogList(query) {
  let list = CATALOG;
  if (query.q) { const q = query.q.toLowerCase(); list = list.filter((m) => m.title.toLowerCase().includes(q)); }
  if (query.genre) list = list.filter((m) => m.genres.includes(query.genre));
  if (query.language) list = list.filter((m) => m.language === query.language);
  if (query.content_type && query.content_type !== "any") list = list.filter((m) => m.content_type === query.content_type);
  if (query.year_from) list = list.filter((m) => m.year >= Number(query.year_from));
  if (query.year_to) list = list.filter((m) => m.year <= Number(query.year_to));
  const sort = query.sort || "popular";
  const sorted = [...list].sort((a, b) => {
    if (sort === "rating") return b.avg_rating - a.avg_rating;
    if (sort === "year") return b.year - a.year;
    if (sort === "title") return a.title.localeCompare(b.title);
    return b.popularity_score - a.popularity_score;
  });
  const page = Math.max(1, Number(query.page) || 1);
  const size = Math.min(100, Number(query.page_size) || 40);
  return { items: sorted.slice((page - 1) * size, page * size).map(card), total: sorted.length, page, page_size: size };
}

function partyPayload(p) {
  const host = userById(p.host_id);
  return { code: p.code, host: publicUser(host), members: p.members.map((id) => publicUser(userById(id))) };
}

let coldFailures = new URLSearchParams(location.search).has("cold") ? 1 : 0;
let coldHealthFailures = coldFailures ? 2 : 0;

const routes = [
  ["GET", /^\/api\/health$/, () => {
    if (coldHealthFailures > 0) { coldHealthFailures--; return fail(503, "Service waking up"); }
    return ok({ status: "ok", model_loaded: true, model_version: db.model_version, dataset_mode: "sample", catalog_size: CATALOG.length });
  }],

  // --- auth ---
  ["POST", /^\/api\/auth\/register$/, (_, body) => {
    const email = String(body.email || "").trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail(422, "Enter a valid email address");
    if (String(body.password || "").length < 6) return fail(422, "Password must be at least 6 characters");
    if (db.users.some((u) => u.email === email)) return fail(409, "An account with this email already exists");
    const user = { id: `u-${uuid().slice(0, 8)}`, email, display_name: String(body.display_name || email.split("@")[0]).trim(), password: body.password, is_admin: false, created_at: iso(Date.now()) };
    db.users.push(user); save();
    return ok({ access_token: `mock-${user.id}`, token_type: "bearer", user: publicUser(user) }, 201);
  }],
  ["POST", /^\/api\/auth\/login$/, (_, body) => {
    const user = db.users.find((u) => u.email === String(body.email || "").trim().toLowerCase());
    if (!user || user.password !== body.password) return fail(401, "Incorrect email or password");
    return ok({ access_token: `mock-${user.id}`, token_type: "bearer", user: publicUser(user) });
  }],
  ["GET", /^\/api\/auth\/me$/, (ctx) => ok(publicUser(ctx.user)), true],

  // --- catalog ---
  ["GET", /^\/api\/movies$/, (ctx) => ok(catalogList(ctx.query))],
  ["GET", /^\/api\/movies\/search$/, (ctx) => {
    const q = String(ctx.query.q || "").toLowerCase();
    const limit = Number(ctx.query.limit) || 10;
    const items = CATALOG.filter((m) => m.title.toLowerCase().includes(q))
      .sort((a, b) => (b.title.toLowerCase().startsWith(q) - a.title.toLowerCase().startsWith(q)) || b.popularity_score - a.popularity_score)
      .slice(0, limit).map(card);
    return ok({ items });
  }],
  ["GET", /^\/api\/movies\/(\d+)$/, (ctx, _, [, id]) => {
    const m = BY_ID.get(Number(id));
    if (!m) return fail(404, "Movie not found");
    const user = ctx.user;
    const similar = CATALOG.map((x) => ({ x, s: similarity(m, x) })).filter(({ s }) => s >= 0).sort((a, b) => b.s - a.s).slice(0, 12).map(({ x }) => card(x));
    return ok({
      ...card(m), directors: m.directors, cast: m.cast, keywords: m.keywords, emotion_arc: m.emotion_arc, decade: m.decade,
      quality_score: m.quality_score, popularity_score: m.popularity_score, trending_velocity: m.trending_velocity, imdb_rating: m.imdb_rating,
      user_rating: user ? ratingsOf(user.id)[m.movie_id]?.rating ?? null : null,
      dismissed: user ? dismissedOf(user.id).includes(m.movie_id) : false,
      similar,
    });
  }],
  ["GET", /^\/api\/meta\/filters$/, () => ok({
    genres: ["Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama", "Fantasy", "Film-Noir", "Horror", "IMAX", "Musical", "Mystery", "Romance", "Sci-Fi", "Thriller", "War", "Western"],
    languages: [...new Set(CATALOG.map((m) => m.language))].map((code) => ({ code, name: LANG_NAMES[code] || code.toUpperCase() })).sort((a, b) => a.name.localeCompare(b.name)),
    age_ratings: AGE_ORDER,
    decades: [1960, 1970, 1980, 1990, 2000, 2010, 2020],
    weather: WEATHER.map(([id, label, icon]) => ({ id, label, icon })),
    time_of_day: ["morning", "afternoon", "evening", "night", "late_night"],
    time_available: [[30, "30 min"], [60, "1 hr"], [90, "1½ hr"], [120, "2 hr"], [150, "2½ hr"], [180, "3 hr+"], [null, "No limit"]].map(([minutes, label]) => ({ minutes, label })),
    occasions: OCCASIONS.map(([id, label, icon]) => ({ id, label, icon })),
    festivals: FESTIVALS.map(([id, label, icon, date]) => ({ id, label, icon, date })),
    emotions: Object.entries(EMOTION_LABELS).map(([id, label]) => ({ id, label })),
    franchises: [...new Set(CATALOG.map((m) => m.collection_name).filter(Boolean))],
    directors: [...new Set(CATALOG.flatMap((m) => m.directors))].slice(0, 100),
    actors: [...new Set(CATALOG.flatMap((m) => m.cast))].slice(0, 150),
    content_types: ["any", "movie", "series"],
  })],
  ["GET", /^\/api\/meta\/people$/, (ctx) => {
    const role = ctx.query.role === "director" ? "directors" : "cast";
    const q = String(ctx.query.q || "").toLowerCase();
    const names = [...new Set(CATALOG.flatMap((m) => m[role]))].filter((n) => n.toLowerCase().includes(q))
      .sort((a, b) => (b.toLowerCase().startsWith(q) - a.toLowerCase().startsWith(q)) || a.localeCompare(b));
    return ok({ items: names.slice(0, Number(ctx.query.limit) || 10) });
  }],
  ["GET", /^\/api\/onboarding\/movies$/, () => {
    const picked = [];
    const genresSeen = {};
    for (const m of [...CATALOG].sort((a, b) => b.popularity_score - a.popularity_score)) {
      const g = m.genres[0];
      if ((genresSeen[g] || 0) >= 4) continue;
      genresSeen[g] = (genresSeen[g] || 0) + 1;
      picked.push(card(m));
      if (picked.length === 30) break;
    }
    return ok({ items: picked });
  }],

  // --- ratings ---
  ["POST", /^\/api\/ratings$/, (ctx, body) => {
    const r = Number(body.rating);
    if (!Number.isFinite(r) || r < 0.5 || r > 5 || Math.round(r * 2) !== r * 2) return fail(400, "Rating must be between 0.5 and 5.0 in steps of 0.5");
    const m = BY_ID.get(Number(body.movie_id));
    if (!m) return fail(404, "Movie not found");
    const created_at = iso(Date.now());
    ratingsOf(ctx.user.id)[m.movie_id] = { rating: r, created_at };
    save();
    return ok({ movie_id: m.movie_id, rating: r, created_at });
  }, true],
  ["GET", /^\/api\/ratings\/me$/, (ctx) => {
    const items = Object.entries(ratingsOf(ctx.user.id)).map(([id, r]) => ({ movie: card(BY_ID.get(Number(id))), rating: r.rating, created_at: r.created_at }))
      .filter((x) => x.movie).sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return ok({ items });
  }, true],
  ["DELETE", /^\/api\/ratings\/(\d+)$/, (ctx, _, [, id]) => { delete ratingsOf(ctx.user.id)[Number(id)]; save(); return noContent(); }, true],

  // --- context + recommendations ---
  ["GET", /^\/api\/context$/, (ctx) => ok(contextResponse(ctx.query))],
  ["GET", /^\/api\/home$/, (ctx) => ok(home(ctx.user.id, ctx.query)), true],
  ["POST", /^\/api\/recommendations$/, (ctx, body) => {
    if (!ctx.user) return fail(400, "User could not be identified");
    return ok(recommend(ctx.user.id, body.context || {}, Math.min(20, body.limit || 20)));
  }],
  ["POST", /^\/api\/recommendations\/(\d+)\/dismiss$/, (ctx, _, [, id]) => {
    const list = dismissedOf(ctx.user.id);
    if (!list.includes(Number(id))) list.push(Number(id));
    db.events.push({ type: "dismiss", user_id: ctx.user.id, movie_id: Number(id), created_at: iso(Date.now()) });
    save();
    return noContent();
  }, true],
  ["DELETE", /^\/api\/recommendations\/(\d+)\/dismiss$/, (ctx, _, [, id]) => {
    db.dismissals[ctx.user.id] = dismissedOf(ctx.user.id).filter((x) => x !== Number(id));
    save();
    return noContent();
  }, true],

  // --- behaviour logging ---
  ["POST", /^\/api\/playback\/start$/, (ctx, body) => {
    const m = BY_ID.get(Number(body.movie_id));
    if (!m) return fail(404, "Movie not found");
    const previous = db.sessions.filter((s) => s.user_id === ctx.user.id && s.movie_id === m.movie_id);
    const session = {
      session_id: uuid(), user_id: ctx.user.id, movie_id: m.movie_id, request_id: body.request_id || null,
      started_at: iso(Date.now()), ended_at: null, drop_off_sec: null, duration_sec: null, completed: false,
      pause_count: 0, seek_back_count: 0, seek_forward_count: 0,
      is_rewatch: previous.some((s) => s.completed), start_number: previous.length + 1,
    };
    db.sessions.push(session); save();
    return ok({ session_id: session.session_id, is_rewatch: session.is_rewatch, start_number: session.start_number });
  }, true],
  ["POST", /^\/api\/playback\/([\w-]+)\/event$/, (ctx, body, [, sid]) => {
    const s = db.sessions.find((x) => x.session_id === sid);
    if (!s) return fail(404, "Session not found");
    if (body.type === "pause") s.pause_count++;
    if (body.type === "seek_back") s.seek_back_count++;
    if (body.type === "seek_forward") s.seek_forward_count++;
    save();
    return noContent();
  }, true],
  ["POST", /^\/api\/playback\/([\w-]+)\/stop$/, (ctx, body, [, sid]) => {
    const s = db.sessions.find((x) => x.session_id === sid);
    if (!s) return fail(404, "Session not found");
    s.ended_at = iso(Date.now());
    s.drop_off_sec = body.position_sec;
    s.duration_sec = body.duration_sec;
    s.completed = !!body.completed;
    save();
    return ok({ session_id: sid, drop_off_sec: s.drop_off_sec, completion_ratio: s.duration_sec ? Math.round((s.drop_off_sec / s.duration_sec) * 1000) / 1000 : 0 });
  }, true],
  ["GET", /^\/api\/playback\/me$/, (ctx) => {
    const items = db.sessions.filter((s) => s.user_id === ctx.user.id).sort((a, b) => (a.started_at < b.started_at ? 1 : -1))
      .map((s) => ({ session_id: s.session_id, movie: card(BY_ID.get(s.movie_id)), started_at: s.started_at, ended_at: s.ended_at, drop_off_sec: s.drop_off_sec, duration_sec: s.duration_sec, completed: s.completed, is_rewatch: s.is_rewatch }));
    return ok({ items });
  }, true],
  ["POST", /^\/api\/events$/, (ctx, body) => {
    for (const e of body.events || []) db.events.push({ ...e, user_id: ctx.user.id, created_at: iso(Date.now()) });
    if (db.events.length > 600) db.events.splice(0, db.events.length - 600);
    save();
    return noContent();
  }, true],
  ["GET", /^\/api\/profile\/insights$/, (ctx) => ok(insights(ctx.user.id)), true],

  // --- watch party ---
  ["POST", /^\/api\/party$/, (ctx, body) => {
    const emails = (body.member_emails || []).map((e) => String(e).trim().toLowerCase()).filter(Boolean);
    const unknown = emails.filter((e) => !db.users.some((u) => u.email === e));
    if (unknown.length) return fail(404, `No CineMatch account for: ${unknown.join(", ")}`);
    let code;
    do { code = Math.random().toString(36).slice(2, 8).toUpperCase(); } while (db.parties[code]);
    const members = [ctx.user.id, ...emails.map((e) => db.users.find((u) => u.email === e).id)];
    db.parties[code] = { code, host_id: ctx.user.id, members: [...new Set(members)] };
    save();
    return ok(partyPayload(db.parties[code]));
  }, true],
  ["POST", /^\/api\/party\/(\w+)\/join$/, (ctx, _, [, code]) => {
    const p = db.parties[code.toUpperCase()];
    if (!p) return fail(404, "No party with that code. Check it and try again.");
    if (!p.members.includes(ctx.user.id)) p.members.push(ctx.user.id);
    save();
    return ok(partyPayload(p));
  }, true],
  ["GET", /^\/api\/party\/(\w+)$/, (ctx, _, [, code]) => {
    const p = db.parties[code.toUpperCase()];
    return p ? ok(partyPayload(p)) : fail(404, "No party with that code. Check it and try again.");
  }, true],
  ["POST", /^\/api\/party\/(\w+)\/recommendations$/, (ctx, body, [, code]) => {
    const p = db.parties[code.toUpperCase()];
    if (!p) return fail(404, "No party with that code. Check it and try again.");
    const members = p.members.map(userById).filter(Boolean);
    const c = body.context || {};
    const ratedByAnyone = new Set(members.flatMap((u) => Object.keys(ratingsOf(u.id)).map(Number)));
    let pool = applyHardFilters(CATALOG.filter((m) => !ratedByAnyone.has(m.movie_id) && !members.some((u) => dismissedOf(u.id).includes(m.movie_id))), c);
    let fallback = false;
    const scored = pool.map((m) => {
      const preds = Object.fromEntries(members.map((u) => [u.display_name, predictStars(u.id, m)]));
      const vals = Object.values(preds);
      const mean = vals.reduce((a, v) => a + v, 0) / vals.length;
      const sd = Math.sqrt(vals.reduce((a, v) => a + (v - mean) ** 2, 0) / vals.length);
      const { boost } = contextBoost(m, c, []);
      return { m, preds, mean, sd, score: mean / 5 - 0.12 * sd + boost };
    }).filter((x) => Object.values(x.preds).every((v) => v >= 2.5)); // average without misery
    if (!scored.length) fallback = true;
    const ranked = (fallback ? trending(CATALOG, 20).map((m) => ({ m, preds: Object.fromEntries(members.map((u) => [u.display_name, predictStars(u.id, m)])), sd: 0, score: m.popularity_score })) : scored.sort((a, b) => b.score - a.score)).slice(0, Math.min(20, body.limit || 20));
    const items = ranked.map(({ m, preds, sd, score }) => {
      const top = Object.entries(preds).sort((a, b) => b[1] - a[1])[0];
      const reason = fallback ? "Popular on CineMatch right now" : sd < 0.35 ? "Everyone should enjoy this" : `${top[0]} will love it, and nobody should mind`;
      return { ...card(m), score: Math.round(Math.min(0.99, score) * 100) / 100, reason, member_scores: preds };
    });
    return ok({ request_id: uuid(), label: fallback ? "Trending now" : `Tonight's pick for ${members.map((u) => u.display_name).join(", ").replace(/, ([^,]*)$/, " and $1")}`, fallback, items, context_used: c });
  }, true],

  // --- admin ---
  ["GET", /^\/api\/admin\/stats$/, (ctx) => (ctx.user.is_admin ? ok(adminStats()) : fail(403, "Admins only")), true],
  ["POST", /^\/api\/admin\/reload-model$/, (ctx) => (ctx.user.is_admin ? ok({ version: db.model_version }) : fail(403, "Admins only")), true],
  ["POST", /^\/api\/admin\/retrain$/, (ctx) => {
    if (!ctx.user.is_admin) return fail(403, "Admins only");
    db.retrain = { status: "running", started_at: Date.now() };
    save();
    return ok({ status: "started" });
  }, true],
  ["GET", /^\/api\/admin\/retrain$/, (ctx) => {
    if (!ctx.user.is_admin) return fail(403, "Admins only");
    const r = db.retrain || { status: "idle" };
    const lines = ["Loading ratings from database…", "Loaded 100,836 ratings for 610 users", "Training SVD (100 factors, 20 epochs)…", "Epoch 20/20  RMSE 0.874", "Writing artifacts to backend/artifacts/v20261002_120412", "Updated current.txt"];
    if (r.status === "running") {
      const elapsed = Date.now() - r.started_at;
      if (elapsed > 7000) {
        db.retrain = { status: "finished", finished_at: Date.now() };
        db.model_version = "v20261002_120412";
        save();
        return ok({ status: "finished", last_log_tail: lines.join("\n") });
      }
      return ok({ status: "running", last_log_tail: lines.slice(0, 1 + Math.floor(elapsed / 1400)).join("\n") });
    }
    return ok({ status: r.status, last_log_tail: r.status === "finished" ? lines.join("\n") : "" });
  }, true],
];

/** Entry point used by api.js: behaves like fetch() + JSON parsing. */
export async function handle(method, url, body, token) {
  // a little latency so skeleton loaders are visible
  await new Promise((r) => setTimeout(r, url.startsWith("/api/events") ? 20 : 140 + Math.random() * 220));

  // simulate the free server sleeping (&cold=1)
  if (coldFailures > 0 && !url.startsWith("/api/health")) {
    coldFailures--;
    throw new TypeError("Failed to fetch (mock cold start)");
  }

  const [path, qs = ""] = url.split("?");
  const query = Object.fromEntries(new URLSearchParams(qs));
  for (const [m, pattern, fn, needsAuth] of routes) {
    if (m !== method) continue;
    const match = path.match(pattern);
    if (!match) continue;
    const user = requireUser(token);
    if (needsAuth && !user) return fail(401, "Not authenticated");
    try {
      // deep-copy so the UI can't accidentally mutate the mock database
      const res = fn({ user, query }, body || {}, match);
      return { status: res.status, data: res.data == null ? null : JSON.parse(JSON.stringify(res.data)) };
    } catch (err) {
      console.error("[mock] handler failed", err);
      return fail(500, "Mock server error");
    }
  }
  return fail(404, `Mock: no route for ${method} ${path}`);
}

/** Wipe the mock database (handy during demos): window.cinematchMockReset() */
export function reset() {
  db = seedDb();
  save();
}
if (typeof window !== "undefined") window.cinematchMockReset = reset;
